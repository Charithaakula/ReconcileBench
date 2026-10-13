"""Score the prose criterion-revision episodes (Table 4, 'prose criterion revision').

Uses reconcilebench/score_criterion.py (sentence finder and the GPT-5.6-SOL
UPDATED/UNCHANGED/WRONG judge) on the final workspaces. Episode closure = both target statements
UPDATED. Judge verdicts are cached in results/judge_cache.json.

    python score_prose_criterion.py '<runs-glob, e.g. runs/prose_criterion/claude-opus-5_*>' <out.json>
"""
import sys, os, json, glob, collections
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'reconcilebench'))
import score_criterion as P

runs, out = sys.argv[1:3]
tasks = os.path.join(REPO, 'tasks', 'general_criterion')
rows = []
for ep in sorted(glob.glob(os.path.join(runs, '*-criterion_*'))):
    inst = os.path.basename(ep).rsplit('_', 1)[0]
    meta = json.load(open(os.path.join(tasks, inst, 'task.json')))['criterion']
    p = os.path.join(ep, meta['rel'])
    labels = {}
    if os.path.exists(p):
        lines = [l.strip() for l in open(p) if l.strip()]
        flagline = next((l for l in lines if P.FLAG_RE.search(l)), None)
        ordline = next((l for l in lines if P.ORD_RE.search(l) and l != flagline
                        and 'ranks' not in l and 'leader of chart' not in l), None)
        for name, hit, ok, nk in (('criterion_truth', ordline, 'old_ord', 'new_ord'),
                                  ('decision_flag', flagline, 'old_flag', 'new_flag')):
            labels[name] = (P.classify(hit, meta[ok], meta[nk], meta['ratio'])
                            if hit else 'MISSING')
    else:
        labels = {'criterion_truth': 'MISSING', 'decision_flag': 'MISSING'}
    correct = sum(v == 'UPDATED' for v in labels.values())
    rows.append(dict(task_id=inst, labels=labels, target_statements_correct=correct,
                     closed=correct == 2))
s = dict(episodes=len(rows), statements_correct=sum(r['target_statements_correct'] for r in rows),
         statements_total=2 * len(rows), closed=sum(r['closed'] for r in rows),
         criterion_truth_correct=sum(r['labels']['criterion_truth'] == 'UPDATED' for r in rows),
         decision_flag_correct=sum(r['labels']['decision_flag'] == 'UPDATED' for r in rows),
         label_counts=dict(collections.Counter(v for r in rows for v in r['labels'].values())))
json.dump(dict(summary=s, episodes=rows), open(out, 'w'), indent=1)
print(json.dumps(s, indent=1))
