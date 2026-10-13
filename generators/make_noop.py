"""Build the already-applied (no-op) episodes: tasks/general_noop/atlas-NN-noop.

The agent receives the same correction turn as the base episode, but its workspace is the base
episode's gold tree: the correction has already been reconciled. Every statement in the turn is
true and nothing needs to change, so the correct response is to verify and edit nothing.

`workspace/` and `gold/` are both relative links to tasks/general/atlas-NN/gold. Scoring
(scorers/score_noop.py) counts every file the agent changed, regenerated or deleted.

    python generators/make_noop.py atlas-01 atlas-02 ...
"""
import argparse, json, os, shutil

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(REPO, 'tasks', 'general')
OUT = os.path.join(REPO, 'tasks', 'general_noop')


def build(base):
    src = os.path.join(BASE, base)
    g = os.path.join(src, 'gold')
    if not os.path.isdir(g):
        print('  %-10s no gold tree -- skipped' % base)
        return False
    dst = os.path.join(OUT, '%s-noop' % base)
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    # Both trees are the base episode's gold: the work is done, and doing it again is the error.
    for sub in ('workspace', 'gold'):
        os.symlink(os.path.relpath(g, dst), os.path.join(dst, sub))

    t = json.load(open(os.path.join(src, 'task.json')))
    t['id'] = '%s-noop' % t.get('id', base)
    t['arm'] = 'noop'
    # Graded offline by scorers/score_noop.py. The in-run atlas grader measures staleness
    # against a correction this workspace has already absorbed, so it would report every
    # site repaired whatever the agent did.
    t['probe'] = 'NOOP'
    json.dump(t, open(os.path.join(dst, 'task.json'), 'w'), indent=1)
    print('  %-10s workspace = gold; correction already applied' % base)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('ids', nargs='+')
    a = ap.parse_args()
    print('%d built' % sum(build(b) for b in a.ids))


if __name__ == '__main__':
    main()
