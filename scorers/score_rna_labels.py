"""Score the BixBench-RNA condition-label episodes (Table 3, 'BixBench-RNA / Metadata').

Grades each final workspace with grade_vis_atlas on the 11 retained site types. Columns:
Direct Δ = sample-sheet correction (source_edit_ok); C1 Δ = json_mean + textval_chart_top3;
C2 Δ = the other 9 retained sites; closure = Direct and all 11 retained sites correct. Run under
the grading interpreter (docs/running.md, "Grading").

    python score_rna_labels.py '<runs-glob, e.g. runs/rna_labels/claude-opus-5_*>' <out.json>
"""
import sys, os, json, glob
sys.dont_write_bytecode = True
RT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RT, 'reconcilebench'))
import grade_vis_atlas as G
RETAINED = ['textsem_superlative', 'list_ranking', 'json_leader', 'json_mean', 'textval_chart_top3',
            'textval_cross_rank', 'textval_atlas_dashboard', 'textval_atlas_overview', 'exec_test',
            'viz_vector', 'textval_atlas_concentration']
C1 = {'json_mean', 'textval_chart_top3'}
runs, out = sys.argv[1:3]
rows = []
for ep in sorted(glob.glob(os.path.join(runs, 'b-0*_*'))):
    tid = os.path.basename(ep).rsplit('_', 1)[0]
    exp = G._resolve(json.load(open(os.path.join(RT, 'tasks', 'rna_labels', tid, 'task.json')))['exp'])
    g = G.grade(ep, exp, only=set(RETAINED))
    oc = {s: g['outcomes'].get(s) for s in RETAINED}
    rows.append(dict(task_id=tid, source_correction_ok=bool(g['source_edit_ok']),
                     retained_outcomes=oc, correct=sum(v == 'ok' for v in oc.values()),
                     affected=len(RETAINED),
                     closed=bool(g['source_edit_ok']) and all(v == 'ok' for v in oc.values())))
n = len(rows)
c1 = sum(r['retained_outcomes'][s] == 'ok' for r in rows for s in C1)
c2 = sum(r['retained_outcomes'][s] == 'ok' for r in rows for s in RETAINED if s not in C1)
src = sum(r['source_correction_ok'] for r in rows); closed = sum(r['closed'] for r in rows)
s = dict(episodes=n, closed=closed, source=src, c1=[c1, 2 * n], c2=[c2, 9 * n],
         table3=[f'{src}/{n}', '--', f'{c1}/{2*n}', '--', f'{c2}/{9*n}', '--', f'{closed}/{n}'])
json.dump(dict(summary=s, episodes=rows), open(out, 'w'), indent=1)
print(json.dumps(s))
