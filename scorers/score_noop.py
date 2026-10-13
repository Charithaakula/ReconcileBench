"""Score the already-applied (no-op) episodes (Table 6, 'Correction already applied').

reconcilebench/score_collateral.score_one against the no-op task, whose workspace and gold are
both the already-corrected tree. 'Abstained' = no prose or data file changed, no figure
regenerated and nothing deleted.

    python score_noop.py '<runs-glob, e.g. runs/noop/claude-opus-5_*>' <out.json>
"""
import sys, os, json, glob
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'reconcilebench'))
import score_collateral as C
runs, out = sys.argv[1:3]
rows = []
for ep in sorted(glob.glob(os.path.join(runs, '*-noop_*'))):
    inst = os.path.basename(ep).rsplit('_', 1)[0]
    r = C.score_one(ep, os.path.join(REPO, 'tasks', 'general_noop', inst))
    rows.append(dict(task_id=inst, changed_prose_data=len(r['collateral']),
                     eligible_prose_data=r['frozen'] - r['nfig'],
                     regenerated_figures=len(r['regen']), eligible_figures=r['nfig'],
                     deleted=len(r['deleted']),
                     closed=not r['collateral'] and not r['regen'] and not r['deleted']))
s = {k: sum(r[k] for r in rows) for k in ('changed_prose_data', 'eligible_prose_data',
     'regenerated_figures', 'eligible_figures', 'deleted', 'closed')}
s['episodes'] = len(rows); s['abstained'] = s.pop('closed')
json.dump(dict(summary=s, episodes=rows), open(out, 'w'), indent=1)
print(json.dumps(s, indent=1))
