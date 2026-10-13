"""Score the retraction episodes (Table 6, 'Correction withdrawn').

reconcilebench/score_revert.score_one against the base workspace in tasks/general (the correct
end state is the workspace as shipped). Per episode: candidate files (files the correction
changed), restored, temporary (still in the corrected state; score_revert's `residue`), third
state, collateral, deleted. Closure = every candidate restored and no collateral.

    python score_retraction.py '<runs-glob, e.g. runs/retraction/claude-opus-5-retraction_*>' <out.json>
"""
import sys, os, json, glob, re, collections
sys.dont_write_bytecode = True
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'reconcilebench'))
import score_revert as R
runs, out = sys.argv[1:3]
rows = []
for ep in sorted(glob.glob(os.path.join(runs, '*-revert-*_*'))):
    tid = os.path.basename(ep).rsplit('_', 1)[0]
    base = os.path.join(REPO, 'tasks', 'general', tid.split('-revert-')[0])
    r = R.score_one(ep, base)
    rows.append(dict(task_id=tid, horizon=int(re.search(r'-revert-(\d+)$', tid).group(1)),
                     candidate_files=r['should_move'], restored=r['restored'],
                     temporary=len(r['residue']), third_state=len(r['third_state']),
                     collateral=len(r['collateral']), deleted=len(r['deleted']),
                     closed=r['restored'] == r['should_move'] and not r['collateral']))
keys = ('candidate_files', 'restored', 'temporary', 'third_state', 'collateral', 'deleted', 'closed')
agg = lambda rs: dict(episodes=len(rs), **{k: sum(x[k] for x in rs) for k in keys})
s = agg(rows)
s['by_horizon'] = {h: agg([x for x in rows if x['horizon'] == h]) for h in sorted({x['horizon'] for x in rows})}
json.dump(dict(summary=s, episodes=rows), open(out, 'w'), indent=1)
print(json.dumps(s, indent=1))
