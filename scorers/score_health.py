"""Score the VisText-Health episodes (Table 3, 'VisText-Health / Evidence').

Sites: the 12 retained site types (SITES below). Deterministic sites use grade_vis_atlas;
affected prose sites use the same GPT-5.6-SOL judge call as score_general_evidence.py
(judge_compare.judge_one), with a cache keyed on the judged text. Preserved prose sites keep the
deterministic no-change grade, as in score_general_evidence.py.

Closure: source corrected AND every affected retained site correct AND every preserved retained
site correct except the historical control_revision_log record (C3-K, not displayed). Columns:
Direct Δ = source correction; C1 = json_mean + textval_chart_top3; C2 = the other retained sites;
C2 K excludes control_revision_log.

Run with the grading interpreter (docs/running.md, "Grading"): exec_test and viz_vector run
sandboxed.

    python score_health.py '<runs-glob, e.g. runs/health/claude-opus-5_*>' <model-dir-suffix> <out.json> <cache-label>
"""
import sys, os, glob, json, hashlib, threading
from concurrent.futures import ThreadPoolExecutor
sys.dont_write_bytecode = True
W = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(W, 'reconcilebench'))
import grade_vis_atlas as GR
from judge_compare import judge_one

SITES = ['textsem_superlative', 'list_ranking', 'json_leader', 'json_mean', 'textval_chart_top3',
         'textval_cross_rank', 'textval_atlas_dashboard', 'textval_atlas_overview', 'exec_test',
         'control_revision_log', 'viz_vector', 'textval_atlas_concentration']
PROSE = {'textsem_superlative', 'textval_chart_top3', 'textval_cross_rank', 'textval_atlas_dashboard',
         'textval_atlas_overview', 'textval_atlas_concentration'}
C1 = {'json_mean', 'textval_chart_top3'}
IDS = ['h-01', 'h-02', 'h-03', 'h-04', 'h-05', 'h-06', 'h-07', 'h-08', 'h-09', 'h-10', 'h-13', 'h-14', 'h-15', 'h-16']

runs, suffix, out, label = sys.argv[1:5]
cache_dir = os.path.join(os.path.dirname(os.path.abspath(out)), f'judge_cache_health_{label}')
os.makedirs(cache_dir, exist_ok=True); lock = threading.Lock()
eps = {}
for d in sorted(glob.glob(os.path.join(runs, f'h-*_{suffix}'))):
    eps[os.path.basename(d).rsplit('_', 1)[0]] = d
missing = [i for i in IDS if i not in eps]
if missing:
    sys.exit(f'missing episodes {missing} under {runs}: score only complete runs')

rows, jobs = {}, []
for tid in IDS:
    task = json.load(open(os.path.join(W, 'tasks', 'health', tid, 'task.json')))
    exp = GR._resolve(task['exp']); broken = set(task['broken'])
    assert exp['gold_root'].startswith(os.path.join(W, 'tasks', 'health')), exp['gold_root']
    g = GR.grade(eps[tid], exp, only=set(SITES))
    oc = {s: g['outcomes'].get(s) == 'ok' for s in SITES}
    rows[tid] = dict(task_id=tid, source_ok=bool(g['source_edit_ok']), outcomes=oc,
                     affected=[s for s in SITES if s in broken], preserved=[s for s in SITES if s not in broken])
    for s in sorted(PROSE & broken):
        rel = GR.rel_for(s, exp['code'], exp['target'])
        jobs.append(dict(tid=tid, site=s, exp=exp, cand=GR._read(eps[tid], rel), grader=g['outcomes'].get(s)))


def judge(j):
    key = hashlib.sha256((j['cand'] or '').encode()).hexdigest()[:16]
    cp = os.path.join(cache_dir, f"{j['tid']}__{j['site']}__{key}.json")
    if os.path.exists(cp):
        c = json.load(open(cp))
        if c.get('judge') is not None:
            return c
    for _ in range(3):
        v, outcome, votes, prompt = judge_one(j['site'], j['exp'], j['cand'], j['grader'])
        if v is not None:
            break
    r = dict(tid=j['tid'], site=j['site'], judge=v, outcome=outcome, grader=j['grader'],
             reasons=[x.get('reason') for x in votes])
    if v is not None:
        with lock:
            json.dump(r, open(cp, 'w'), indent=1)
    return r


with ThreadPoolExecutor(max_workers=8) as ex:
    judged = list(ex.map(judge, jobs))
undecided = [r for r in judged if r['judge'] is None]
if undecided:
    sys.exit(f'{len(undecided)} prose judgments undecided: {[(r["tid"], r["site"]) for r in undecided]}')
for r in judged:
    rows[r['tid']]['outcomes'][r['site']] = bool(r['judge'])

c1d, c1k, c2d, c2k = [0, 0], [0, 0], [0, 0], [0, 0]
closed = src = 0
for tid in IDS:
    r = rows[tid]; oc = r['outcomes']
    for s in r['affected']:
        b = c1d if s in C1 else c2d; b[0] += oc[s]; b[1] += 1
    for s in r['preserved']:
        if s == 'control_revision_log':
            continue
        b = c1k if s in C1 else c2k; b[0] += oc[s]; b[1] += 1
    r['closed'] = r['source_ok'] and all(oc[s] for s in r['affected']) and \
        all(oc[s] for s in r['preserved'] if s != 'control_revision_log')
    closed += r['closed']; src += r['source_ok']
f = lambda x: f'{x[0]}/{x[1]}'
summary = dict(episodes=len(IDS), closed=closed, source=src, c1d=c1d, c1k=c1k, c2d=c2d, c2k=c2k,
               judged=len(judged),
               table3=[f'{src}/{len(IDS)}', '--', f(c1d), f(c1k), f(c2d), f(c2k), f'{closed}/{len(IDS)}'])
json.dump(dict(summary=summary, episodes=list(rows.values()), judge_rows=judged), open(out, 'w'), indent=1)
print(json.dumps(summary))
