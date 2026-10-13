"""Score the prose evidence-correction episodes (Table 4, 'prose evidence correction').

For the two C3 sites (textsem_ratio_threshold = criterion claim, textsem_flag_withdrawal =
dependent review flag), a site the event changes is scored by the GPT-5.6-SOL prose judge
(judge_compare.py output, outcome == "yes"); a site the event leaves unchanged uses the same run's
preservation grade (outcome == "ok"). Episode closure = both sites correct.

    python score_prose_evidence.py <judge.json> <res_glob> <out.json>
"""
import sys, os, json, glob
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITES = ('textsem_ratio_threshold', 'textsem_flag_withdrawal')
judge_path, res_glob, out = sys.argv[1:4]
judge = {(r['task'], r['site']): r for r in json.load(open(judge_path)) if r['site'] in SITES}
run = {}
for p in glob.glob(res_glob):
    for line in open(p):
        if line.strip():
            r = json.loads(line); run[r['task_id']] = r
rows = []
for n in range(1, 21):
    tid = f'atlas-{n:02d}'
    task = json.load(open(os.path.join(REPO, 'tasks', 'general', tid, 'task.json')))
    broken = set(task['exp']['broken'])
    fields = []
    for site in SITES:
        if site in broken:
            row = judge[(tid, site)]
            fields.append(dict(site=site, operation='change', correct=row['outcome'] == 'yes',
                               source='prose_judge'))
        else:
            fields.append(dict(site=site, operation='preserve',
                               correct=run[tid]['grade']['outcomes'][site] == 'ok',
                               source='same_run_preservation_grade'))
    rows.append(dict(task_id=tid, fields=fields, closed=all(f['correct'] for f in fields)))
ch = lambda s: [f for r in rows for f in r['fields'] if f['site'] == s and f['operation'] == 'change']
s = dict(episodes=len(rows), closed=sum(r['closed'] for r in rows),
         crit_correct=sum(f['correct'] for f in ch(SITES[0])), crit_n=len(ch(SITES[0])),
         flag_correct=sum(f['correct'] for f in ch(SITES[1])), flag_n=len(ch(SITES[1])))
json.dump(dict(summary=s, episodes=rows), open(out, 'w'), indent=1)
print(json.dumps(s))
