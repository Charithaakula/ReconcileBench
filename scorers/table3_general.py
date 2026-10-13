"""Table 3 VisText-General rows (Evidence, Rule) from the evidence and typed-record scores.

Evidence: Direct Δ = source correction; Direct K = held-fixed review threshold; C1 Δ = json_mean +
textval_chart_top3; C2 Δ = the other affected retained sites; C2 K = preserved retained sites
except control_revision_log (that dated record is C3-K and is not shown). Closure = source
correction, every affected retained site, the held-fixed threshold and the C2-K checks.
Rule: Direct Δ = new threshold applied; C1 K = observed ratio unchanged; closure = both.

    python table3_general.py <evidence.json> <records.json> <results-dir> <model>

Writes <results-dir>/general_evidence/scored_<model>.json and general_rule/scored_<model>.json.
"""
import sys, json, os
evidence, records, out_dir, cfg = sys.argv[1:5]
C1 = {'json_mean', 'textval_chart_top3'}
ev = json.load(open(evidence))['episodes']
direct_d = sum(e['authority_ok'] for e in ev)
direct_k = sum(e['typed_preservation_ok'] for e in ev)
c1 = [0, 0]; c2 = [0, 0]; c2k = [0, 0]; closed = 0
tasks = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tasks', 'general')
for e in ev:
    broken = set(json.load(open(f"{tasks}/{e['workspace']}/task.json"))['exp']['broken'])
    oc = e['ordinary_outcomes']; ok_all = True; kp = True
    for site, good in oc.items():
        if site in broken:
            bucket = c1 if site in C1 else c2
            bucket[0] += good; bucket[1] += 1; ok_all &= good
        elif site != 'control_revision_log':
            c2k[0] += good; c2k[1] += 1; kp &= good
    closed += e['authority_ok'] and ok_all and e['typed_preservation_ok'] and kp
pol = [e for e in json.load(open(records))['episodes'] if e['transition'] == 'policy']
r_direct = sum(e['authority_ok'] for e in pol); r_k = sum(e['preservation_ok'] for e in pol)
r_closed = sum(e['authority_ok'] and e['preservation_ok'] for e in pol)
f = lambda a, b: f'{a}/{b}'
evs = dict(episodes=len(ev), closed=closed, c1=c1, c2=c2, c2k=c2k,
           table3=[f(direct_d, len(ev)), f(direct_k, len(ev)), f(*c1), '--', f(*c2), f(*c2k),
                   f(closed, len(ev))])
rule = dict(episodes=len(pol), closed=r_closed,
            table3=[f(r_direct, len(pol)), '--', '--', f(r_k, len(pol)), '--', '--', f(r_closed, len(pol))])
for name, s in (('general_evidence', evs), ('general_rule', rule)):
    os.makedirs(os.path.join(out_dir, name), exist_ok=True)
    json.dump(dict(summary=s), open(os.path.join(out_dir, name, f'scored_{cfg}.json'), 'w'), indent=1)
    print(name, json.dumps(s))
