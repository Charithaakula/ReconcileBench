"""Add the end-of-episode grade to records from harnesses that do not compute one.

mini-SWE-agent's runner grades every ATLAS episode in place with
`grade_vis_atlas(workspace, task['exp'])` (harness/run_tasks.py) and stores it as the record's
`grade`; scorers/score_prose_evidence.py reads its preservation outcomes. The Codex CLI and
Claude Code wrappers record no grade, so this makes the same call on each valid record's final
workspace and writes the records with `grade` added. Run it with the grading interpreter
(docs/running.md, "Grading").

    python grade_offline_atlas.py <res.jsonl> <tasks-dir> <out.jsonl>
"""
import sys, os, json
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'reconcilebench'))
sys.dont_write_bytecode = True
from grade_vis_atlas import grade as grade_vis_atlas


def grade(rec, tasks):
    task = json.load(open(os.path.join(tasks, rec['task_id'], 'task.json')))
    assert task.get('probe') == 'ATLAS', (rec['task_id'], task.get('probe'))
    g = grade_vis_atlas(rec['workspace'], task['exp']); g['arm'] = task['arm']
    return g


if __name__ == '__main__':
    res, tasks, out = sys.argv[1:4]
    rows = [json.loads(x) for x in open(res) if x.strip()]
    with open(out, 'w') as fh:
        for r in rows:
            if r.get('valid'):
                r = dict(r, grade=grade(r, tasks))
            fh.write(json.dumps(r) + '\n')
    print(f'{len(rows)} records graded -> {out}')
