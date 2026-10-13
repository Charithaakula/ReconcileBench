"""Build the prose criterion-revision episodes: tasks/general_criterion/atlas-NN-criterion.

The chart data do not change; the review criterion does. Each atlas states a multiple of the
median that the leading value must reach for a finding to hold and for a review flag to apply.
These episodes revise both multiples so that both conclusions flip against the unchanged data: if
the shipped text says the flag applies, the revised criterion must withdraw it, and vice versa.
An agent that keeps every threshold-like number fixed is wrong, and so is one that edits the data
instead of the criterion.

Gold is the shipped tree with only the two criterion sentences rewritten. `workspace/` is a link
to the base workspace in tasks/general/atlas-NN. Scoring is scorers/score_prose_criterion.py.

    python generators/make_criterion.py atlas-01 atlas-02 ...
"""
import argparse, csv, json, os, re, shutil

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(REPO, 'tasks', 'general')
OUT = os.path.join(REPO, 'tasks', 'general_criterion')


def _fmt(x):
    return ('%g' % x)


def chart_stats(ws, target):
    """Leader and median of the target chart, as the workspaces define them: descending sort,
    element at len//2 (statistics.median averages the two middle values on even lengths)."""
    p = os.path.join(ws, 'data', target, 'values.csv')
    vals = []
    for row in csv.DictReader(open(p)):
        for k in ('value', 'v', 'amount'):
            if k in row:
                try:
                    vals.append(float(row[k]))
                except (TypeError, ValueError):
                    pass
                break
    sv = sorted(vals, reverse=True)
    return sv[0], sv[len(sv) // 2]


ORD_RE = re.compile(r'^- (?:The leading entry stands \*\*more than ([\d.]+) times\*\* the chart '
                    r'median\.|No entry stands more than ([\d.]+) times the chart median\.)$')
FLAG_RE = re.compile(r'^- (?:Because the leader exceeds ([\d.]+) times the chart median, this '
                     r'chart carries a \*\*review flag\*\*\.|The leader is within ([\d.]+) '
                     r'times the chart median, so no review flag applies\.)$')


def rewrite(txt, lead, med, t_ord, t_flag):
    out = []
    for line in txt.split('\n'):
        if ORD_RE.match(line):
            out.append('- The leading entry stands **more than %s times** the chart median.'
                       % _fmt(t_ord) if lead >= t_ord * med else
                       '- No entry stands more than %s times the chart median.' % _fmt(t_ord))
        elif FLAG_RE.match(line):
            out.append('- Because the leader exceeds %s times the chart median, this chart '
                       'carries a **review flag**.' % _fmt(t_flag) if lead >= t_flag * med else
                       '- The leader is within %s times the chart median, so no review flag '
                       'applies.' % _fmt(t_flag))
        else:
            out.append(line)
    return '\n'.join(out)


def build(base):
    src = os.path.join(BASE, base)
    ws = os.path.join(src, 'workspace')
    t = json.load(open(os.path.join(src, 'task.json')))
    target = t['exp']['target']
    lead, med = chart_stats(ws, target)
    ratio = lead / med

    # Find the file carrying the two sentences and the thresholds it currently states.
    hit = None
    for d, _, fs in os.walk(ws):
        for f in fs:
            if not f.endswith('.md'):
                continue
            p = os.path.join(d, f)
            txt = open(p).read()
            o = next((m for m in (ORD_RE.match(l) for l in txt.split('\n')) if m), None)
            fl = next((m for m in (FLAG_RE.match(l) for l in txt.split('\n')) if m), None)
            if o and fl:
                hit = (os.path.relpath(p, ws), txt,
                       float(o.group(1) or o.group(2)), float(fl.group(1) or fl.group(2)))
                break
        if hit:
            break
    if not hit:
        print('  %-10s no threshold sentences found -- skipped' % base)
        return False
    rel, txt, old_ord, old_flag = hit

    # Choose multiples that flip both conclusions against the unchanged data.
    new_ord = 2.0 if ratio < old_ord else max(2.0, round(ratio) + 2.0)
    new_flag = 2.0 if ratio < old_flag else max(2.0, round(ratio) + 2.0)
    if (lead >= new_ord * med) == (lead >= old_ord * med) and \
       (lead >= new_flag * med) == (lead >= old_flag * med):
        print('  %-10s no flipping multiple available (ratio %.2f) -- skipped' % (base, ratio))
        return False

    dst = os.path.join(OUT, '%s-criterion' % base)
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    os.symlink(os.path.relpath(ws, dst), os.path.join(dst, 'workspace'))
    # Gold is the shipped tree with only the two criterion sentences rewritten: the data did
    # not change, so nothing derived from the data may change either.
    gold = os.path.join(dst, 'gold')
    shutil.copytree(ws, gold, symlinks=False)
    open(os.path.join(gold, rel), 'w').write(rewrite(txt, lead, med, new_ord, new_flag))

    # Phrased like the data corrections: a statement of fact, with no instruction about what
    # to edit and no file named.
    turn = ("A note on our review criteria, not on the data: the order-of-magnitude multiple "
            "we flag against is now %s times the chart median, revised from %s, and the "
            "review-flag multiple is now %s, revised from %s. The underlying figures are "
            "unchanged and no source of record has been revised."
            % (_fmt(new_ord), _fmt(old_ord), _fmt(new_flag), _fmt(old_flag)))
    t['turns'] = t['turns'][:-1] + [turn]
    t['id'] = '%s-criterion' % t.get('id', base)
    t['arm'] = 'criterion'
    t['criterion'] = dict(rel=rel, old_ord=old_ord, new_ord=new_ord, old_flag=old_flag,
                          new_flag=new_flag, lead=lead, med=med, ratio=ratio)
    json.dump(t, open(os.path.join(dst, 'task.json'), 'w'), indent=1)
    print('  %-10s ratio %5.2f  ord %g->%g  flag %g->%g   (%s)'
          % (base, ratio, old_ord, new_ord, old_flag, new_flag, rel))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('ids', nargs='+')
    a = ap.parse_args()
    n = sum(build(b) for b in a.ids)
    print('%d built' % n)


if __name__ == '__main__':
    main()
