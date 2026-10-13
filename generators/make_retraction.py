"""Build the retraction episodes: tasks/general_retraction/atlas-NN-revert-{2,6,12}.

Each episode delivers the base episode's correction, then N intervening questions about other
charts, then a turn withdrawing the correction and restoring the original value. The correct
final workspace is the one the agent started from, so the reference is the shipped tree itself.
The intervening turns keep the withdrawal out of the immediate context: a back-to-back retraction
would test recall of the last message rather than maintenance of the workspace.

`workspace/` and `gold/` are relative links to the base episode in tasks/general/atlas-NN, so the
episodes differ from it only in their turns. Scoring is scorers/score_retraction.py.

    python generators/make_retraction.py [--gaps 2,6,12] atlas-01 atlas-02 ...
"""
import argparse, csv, json, os, shutil

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(REPO, 'tasks', 'general')
OUT = os.path.join(REPO, 'tasks', 'general_retraction')


def filler_turns(taskdir, n):
    """n questions that require reading the workspace and change nothing that is scored.

    Generated from the atlas's own manifest, so they name real charts. They avoid the target
    chart: a question that made the agent read the corrected chart would prime it.
    """
    ws = os.path.join(taskdir, 'workspace')
    exp = json.load(open(os.path.join(taskdir, 'task.json')))['exp']
    target = exp.get('target') if isinstance(exp, dict) else None
    meta = list(csv.DictReader(open(os.path.join(ws, 'data/charts.csv'))))
    others = [m for m in meta if m['id'] != target]
    Q = []
    for m in others:
        Q.append("What unit does chart `%s` report its values in?" % m['id'])
        Q.append("How many entries does chart `%s` list?" % m['id'])
        Q.append("Which entry leads chart `%s`?" % m['id'])
    Q += [
        "Does `notes/methodology.md` say anything about smoothing or imputation?",
        "How many charts does this atlas catalogue?",
        "Which file is the source of record for chart `%s`?" % others[0]['id'],
        "Does `analysis/revision-log.md` record anything from before this session?",
        "List the top-level directories in this workspace.",
    ]
    return Q[:n]


def change_turn(taskdir):
    return json.load(open(os.path.join(taskdir, 'task.json')))['turns'][-1]


def revert_turn(taskdir):
    """Withdraw the correction and restore the original value, in a maintainer's register."""
    exp = json.load(open(os.path.join(taskdir, 'task.json')))['exp']
    eds = (exp.get('edits') or []) if isinstance(exp, dict) else []
    if not eds:
        return None
    e = eds[0]
    if e.get('kind') == 'delete':
        what = ("The withdrawal of the %s entry was issued in error -- it was not "
                "double-counted. Please restore it at its original value of %s." %
                (e['entity'], e['old']))
    else:
        what = ("The revision to the %s entry was issued in error. Please restore its "
                "original value of %s." % (e['entity'], e['old']))
    return ("Correction to the previous revision: %s Bring the workspace back into line with "
            "the sources of record." % what)


def build(base, gap):
    if not (base.startswith('atlas-') and base[6:].isdigit()):
        raise SystemExit('%s is not a base episode' % base)
    src = os.path.join(BASE, base)
    arm = 'revert-%d' % gap
    dst = os.path.join(OUT, '%s-%s' % (base, arm))
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    for sub in ('workspace', 'gold'):
        s = os.path.join(src, sub)
        if os.path.exists(s):
            os.symlink(os.path.relpath(s, dst), os.path.join(dst, sub))

    t = json.load(open(os.path.join(src, 'task.json')))
    rev = revert_turn(src)
    if rev is None:
        raise SystemExit('%s has no edits to revert' % base)
    turns = [t['turns'][0]] + t['turns'][1:-1] + [change_turn(src)] + filler_turns(src, gap) + [rev]

    t['turns'] = turns
    t['id'] = '%s-%s' % (t.get('id', base), arm)
    t['arm'] = arm
    # Graded offline by scorers/score_retraction.py. The in-run atlas grader measures
    # staleness against the correction, which these episodes withdraw.
    t['probe'] = 'REVERT'
    json.dump(t, open(os.path.join(dst, 'task.json'), 'w'), indent=1)
    print('  %-26s %2d turns' % (os.path.basename(dst), len(turns)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--gaps', default='2,6,12',
                    help='numbers of intervening turns between the correction and its withdrawal')
    ap.add_argument('ids', nargs='+')
    a = ap.parse_args()
    for base in a.ids:
        for gap in a.gaps.split(','):
            build(base, int(gap))


if __name__ == '__main__':
    main()
