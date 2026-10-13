"""Table 3 'BixBench-RNA / Mixed' row from RNA mixed run records.

Field layers are the paper's: direct, C1 (computation), C2 (relation or representation) and C3
(conclusion or action), plus the protected fields (dated history and unaffected controls). The
compound case's manuscript_state and project_handoff fields are not part of the row. Closure
requires every direct change, every C1 and C2 change, and every direct, C1 and C2 preservation.
Direct K counts the cases whose three protected fields all hold.

    python table3_rna_mixed.py <out.json> <res.jsonl> [<res.jsonl> ...]
"""
import sys, json
out, paths = sys.argv[1], sys.argv[2:]
rows = [json.loads(l) for p in paths for l in open(p) if l.strip()]
cnt = {}
closed = protected_cases = 0
for r in rows:
    fs = [f for f in r['grade']['field_outcomes'] if f['id'] not in {'manuscript_state', 'project_handoff'}]
    for f in fs:
        k = (f['role'], f['operation']); a, b = cnt.get(k, (0, 0)); cnt[k] = (a + f['correct'], b + 1)
    ok = lambda roles, op: all(f['correct'] for f in fs if f['role'] in roles and f['operation'] == op)
    closed += ok({'direct'}, 'change') and ok({'C1', 'C2'}, 'change') and ok({'direct', 'C1', 'C2'}, 'preserve')
    protected_cases += all(f['correct'] for f in fs if f['role'] == 'protected')
g = lambda role, op: '/'.join(map(str, cnt.get((role, op), (0, 0)))) if (role, op) in cnt else '--'
s = dict(episodes=len(rows), closed=closed, counts={f'{k[0]}-{k[1]}': v for k, v in cnt.items()},
         table3=[g('direct', 'change'), f'{protected_cases}/{len(rows)}', g('C1', 'change'), g('C1', 'preserve'),
                 g('C2', 'change'), g('C2', 'preserve'), f'{closed}/{len(rows)}'])
json.dump(dict(summary=s, episodes=[r['task_id'] for r in rows]), open(out, 'w'), indent=1)
print(json.dumps(s))
