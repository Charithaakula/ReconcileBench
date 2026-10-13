"""Run the prose judge over the final workspaces of recorded episodes.

Writes a record per (episode, site) holding the judge's verdict, votes and reasons, the
deterministic grader's verdict beside it, and the inputs interpolated into the prompt.
scorers/score_prose_evidence.py reads these records.

    python reconcilebench/judge_compare.py --runs 'runs/prose_evidence/<model>_*' --base-only --out <judge.json>

Judge calls are independent, so they run in a pool. Each worker returns its own result, so a
site's votes stay attached to that site whatever order the calls complete in.
"""
import os, sys, json, argparse, glob, hashlib, re
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import grade_vis_atlas as GR
import claim_rules as CR
import judge_claim as J


def judge_one(site, exp, cand, grader=None):
    """One site, self-contained: returns (verdict, outcome, votes, prompt)."""
    if cand is None and CR.PRESENCE.get(site) == 'retirable':
        # There is no text to judge because the artifact was retired, and for a retirable
        # claim retiring it is one of the two correct repairs -- the note's own last sentence
        # invites it. Whether THIS removal was deliberate rather than a directory being
        # deleted is a question about the file system, not about prose, so it is settled by
        # the deterministic check and not sent to the judge, where it would come back
        # `no-prompt` and be counted as a failure.
        return (grader == 'ok'), ('retired' if grader == 'ok' else 'deleted'), [], None
    user, rel, k = J.build_prompt(site, exp, cand)
    if user is None:
        return None, 'no-prompt', [], None
    votes, raw = [], []
    for _ in range(J.VOTES):
        v, reason, _reply = J._ask(J.SYSTEM, user)
        raw.append(dict(correct=v, reason=reason))
        if v is not None:
            votes.append(v)
    if len(votes) < min(2, J.VOTES):
        return None, 'undecided-no-quorum', raw, user
    yes, no = sum(votes), len(votes) - sum(votes)
    if yes == no:
        return None, 'undecided-tie', raw, user
    return (yes > no), ('yes' if yes > no else 'no'), raw, user


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runs', required=True, help='glob of run folders holding <id>_<model> workspaces')
    ap.add_argument('--limit', type=int, default=0, help='0 = every episode found')
    ap.add_argument('--base-only', action='store_true',
                    help='only episodes whose id matches --base-pattern')
    ap.add_argument('--tasks', default='tasks/general',
                    help='the task folder the episodes were run from. Episodes are matched to '
                         'task folders by name, so the wrong folder judges nothing.')
    ap.add_argument('--base-pattern', dest='base_pattern', default=r'atlas-\d+',
                    help='the id pattern --base-only keeps')
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    eps = []
    for rd in sorted(glob.glob(a.runs)):
        if not os.path.isdir(rd):
            continue
        for d in sorted(os.listdir(rd)):
            p = os.path.join(rd, d)
            if not os.path.isdir(p) or '_' not in d:
                continue
            tid, model = d.rsplit('_', 1)
            if a.base_only and not re.fullmatch(a.base_pattern, tid):
                continue
            if os.path.exists(os.path.join(REPO, a.tasks, tid, 'task.json')):
                eps.append((tid, model, p, os.path.basename(rd)))
    if a.limit:
        eps = eps[:a.limit]
    print('%d episodes' % len(eps), flush=True)

    jobs = []
    for i, (tid, model, w, rd) in enumerate(eps, 1):
        exp = GR._resolve(json.load(open(os.path.join(
            REPO, a.tasks, tid, 'task.json')))['exp'])
        sites = sorted(set(exp['broken']) & set(CR.RULES))
        g = GR.grade(w, exp, only=set(sites))     # only the sites we are judging
        print('[%3d/%d] %-26s %-14s %-12s grader %s' % (i, len(eps), tid, model, rd, g['rr']),
              flush=True)
        for site in sites:
            rel = GR.rel_for(site, exp['code'], exp['target'])
            jobs.append(dict(task=tid, model=model, run=rd, episode=os.path.basename(w),
                             site=site, rel=rel, grader=g['outcomes'].get(site),
                             exp=exp, cand=GR._read(w, rel) if rel else None))

    print('\n%d sites to judge, %d workers, %d vote(s) each'
          % (len(jobs), a.workers, J.VOTES), flush=True)

    def work(j):
        v, outcome, raw, prompt = judge_one(j['site'], j['exp'], j['cand'], j['grader'])
        R = CR.RULES[j['site']]
        return dict(task=j['task'], model=j['model'], run=j['run'], episode=j['episode'],
                    site=j['site'], rel=j['rel'], grader=j['grader'], judge=v,
                    outcome=outcome, votes=raw, prompt=prompt,
                    rule=dict(defn=R['defn'], quantity=R['quantity'], prose=R['prose'],
                              expr=R['expr'], fixed=R.get('fixed'),
                              presence=CR.PRESENCE.get(j['site'], 'required')),
                    raw=[x.get('reason') for x in raw],
                    want=CR.want_text(j['site'], j['exp']))

    rows, done = [], 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for r in ex.map(work, jobs):
            rows.append(r)
            done += 1
            if done % 50 == 0:
                d = sum(1 for x in rows if (x['grader'] == 'ok') != (x['judge'] is True))
                print('  %d/%d judged, %d disagree so far' % (done, len(jobs), d), flush=True)

    json.dump(rows, open(a.out, 'w'), indent=1)
    json.dump(J.provenance(), open(a.out.replace('.json', '.meta.json'), 'w'), indent=1)
    dis = [r for r in rows if (r['grader'] == 'ok') != (r['judge'] is True)]
    und = [r for r in rows if r['judge'] is None]
    print('\n%d rows -> %s' % (len(rows), a.out))
    print('agree %d   disagree %d   undecided %d'
          % (len(rows) - len(dis), len(dis), len(und)))

    # A judge that cannot reach the API returns None for every site, and None counts as a
    # wrong claim downstream -- so a broken key would read as a low benchmark score rather
    # than as a failure. Refuse to exit clean.
    failed = sum(1 for r in rows
                 for v in r.get('votes', [])
                 if (v.get('reason') or '').startswith('call failed'))
    if failed:
        print('\nABORT: %d/%d judge calls failed at the API (e.g. missing OPENAI_API_KEY).'
              % (failed, sum(len(r.get('votes', [])) for r in rows)))
        sys.exit(2)
    if len(rows) and len(und) > 0.05 * len(rows):
        print('\nABORT: %d/%d sites undecided (>5%%); the verdicts are not usable.'
              % (len(und), len(rows)))
        sys.exit(3)


if __name__ == '__main__':
    main()
