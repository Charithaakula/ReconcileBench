"""Shared helpers for the VisText workspace generators.

The certified VisText chart pool, the per-chart facts every derived file is written from, the
check that a harvested caption is true of its chart, and the figure build step. gen_vis_atlas.py
builds the atlases from these; grade_vis_atlas.py shares the number format and the superlative
vocabulary.
"""
import os, sys, math, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.environ.get('RB_RENDER_PYTHON') or sys.executable   # the interpreter that renders figures
VISTEXT = os.environ.get('RB_VISTEXT') or os.path.join(HERE, '..', 'sources', 'vistext', 'data_train.json')

SUP_W = r'(?:highest|largest|greatest|most|top|peak|peaked|maximum|leading|biggest)'
MIN_W = r'(?:lowest|smallest|least|fewest|minimum)'


def nice_ceiling(v):
    """Smallest 1/2/2.5/5 x 10^k at or above v: the renderer's axis rule."""
    if v <= 0:
        return 1.0
    k = math.floor(math.log10(v))
    for m in (1.0, 2.0, 2.5, 5.0, 10.0):
        c = m * 10 ** k
        if c >= v - 1e-12:
            return c
    return 10.0 ** (k + 1)


def facts(rows):
    """Every derived fact, as one pure function of the source."""
    vals = [v for _, v in rows]
    n = len(rows)
    mean = round(sum(vals) / n, 1)
    above = sum(1 for v in vals if v > mean)
    share = int(round(100.0 * above / n))
    return dict(
        argmax=max(rows, key=lambda p: p[1])[0],
        argmin=min(rows, key=lambda p: p[1])[0],
        order=[l for l, _ in sorted(rows, key=lambda p: (-p[1], p[0]))],
        axis=nice_ceiling(max(vals)),
        mean=mean, above=above, share=share,
        verdict='MAJORITY' if share > 50 else 'MINORITY',
    )


def _fmt(v):
    return str(int(v)) if float(v) == int(v) else str(v)


def load_pool(min_rows=6, max_rows=20):
    """Certified VisText bar charts inside the row bounds, one record per image."""
    import vistext as V
    pool, seen = [], set()
    for rec in V.load(VISTEXT):
        u = V.usable(rec)
        if not u or u['ctype'] != 'bar' or not min_rows <= len(u['rows']) <= max_rows:
            continue
        if any(v <= 0 for _, v in u['rows']):
            continue
        if len({l for l, _ in u['rows']}) != len(u['rows']):
            continue
        if u['img_id'] in seen:
            continue
        seen.add(u['img_id'])
        pool.append(u)
    return pool


def _caption_ok(u, f):
    """The harvested caption must assert the argmax (and ideally the argmin), and those
    assertions must be true of the starting data.

    The caption is a person's prose, and some captions are already wrong (one miscounts a
    band). A starting workspace that is not internally consistent cannot be used: the grader
    would score a model for failing to repair something that was never consistent.
    """
    cap = u['caption']
    sents = [s for s in re.split(r'(?<=[.!?])\s+', cap) if s.strip()]
    sup = [s for s in sents if re.search(SUP_W, s, re.I)]
    mn = [s for s in sents if re.search(MIN_W, s, re.I)]
    if not sup:
        return None
    amax, amin = f['argmax'], f['argmin']
    # the argmax must be named in a superlative sentence, and no OTHER row may be
    if not any(amax.lower() in s.lower() for s in sup):
        return None
    others = [l for l, _ in u['rows'] if l != amax]
    if any(o.lower() in s.lower() for s in sup for o in others if len(o) > 4):
        return None
    has_min = bool(mn) and any(amin.lower() in s.lower() for s in mn)
    if has_min:
        others = [l for l, _ in u['rows'] if l != amin]
        if any(o.lower() in s.lower() for s in mn for o in others if len(o) > 4):
            has_min = False
    return dict(has_min=has_min)


def build_png(root, script='scripts/render_chart.py'):
    r = subprocess.run([os.path.abspath(VENV_PY), script],
                       cwd=root, capture_output=True, text=True)
    return r.returncode == 0, r.stderr
