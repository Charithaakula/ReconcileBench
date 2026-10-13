"""Build a VisText-General workspace: an atlas of published charts with a derived layer.

The atlas holds 30-60 certified VisText charts (`N_CHARTS` by default), each with a source of
record and its own derived files, plus atlas-wide files computed over every chart. One
authoritative correction is applied to one chart. The workspace is too large to read in a single
command, so finding the files the correction invalidates is part of the task.

    data/charts.csv                    manifest: id, title, unit
    data/<id>/values.csv               one source of record per chart
    analysis/INDEX.md                  workstream codename -> chart title
    analysis/<code>-review.md          harvested human caption
    analysis/<code>-ranking.md         entries ranked by value
    analysis/<code>-stats.json         leader, mean, above-mean, share, verdict
    analysis/<code>-segment.md         leader against runner-up
    analysis/<code>-profile.md         in-chart distribution sweeps
    analysis/<code>-narrative.md       commentary                  (corrected chart only)
    analysis/<code>-relations.md       rank, ratios, thresholds    (corrected chart only)
    analysis/<code>-editorial.md       the 'dominates' claim       (corrected chart only)
    analysis/overview.md               atlas-wide: highest single value
    analysis/atlas-stats.md            atlas-wide: aggregates over chart leaders
    analysis/leader-index.md           atlas-wide: mean of chart leaders
    analysis/portfolio-brief.md        atlas-wide: count of leaders above a threshold
    analysis/record-holder.md          atlas-wide: who holds the record
    analysis/revision-log.md           dated history; must not be rewritten
    docs/dashboard.md                  one row per chart, from scripts/build_dashboard.py
    figs/<id>.png                      built by scripts/render_charts.py
    figs/<id>.svg                      hand-maintained              (corrected chart only)
    tests/test_atlas.py                asserts leader and value     (corrected chart only)
    notes/methodology.md               depends on no value

The corrected chart is the one holding the global maximum, so the correction breaks the
atlas-wide files as well as that chart's own derived files. Every other chart's files are
preservation sites and must not change. `render_pre` writes the shipped workspace and `perfect`
writes the corrected reference (gold).
"""
import os, sys, csv, json, math, shutil, hashlib, subprocess, re

HERE = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.environ.get('RB_RENDER_PYTHON') or sys.executable   # interpreter with matplotlib 3.9.4
from gen_vis import facts, _fmt, _caption_ok, build_png, load_pool, nice_ceiling

N_CHARTS = 50

RENDER = '''"""Regenerates every figure in figs/ from data/. Run after changing any source."""
import csv, math, os, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def nice_ceiling(v):
    k = math.floor(math.log10(v))
    for m in (1.0, 2.0, 2.5, 5.0, 10.0):
        c = m * 10 ** k
        if c >= v - 1e-12:
            return c
    return 10.0 ** (k + 1)


meta = {r["id"]: r for r in csv.DictReader(open("data/charts.csv"))}
for cid, m in sorted(meta.items()):
    rows = [(r[0], float(r[1])) for r in
            list(csv.reader(open("data/%s/values.csv" % cid)))[1:]]
    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=100)
    y = list(range(len(rows)))[::-1]
    ax.barh(y, [v for _, v in rows], color="#4c78a8")
    ax.set_yticks(y)
    ax.set_yticklabels([l for l, _ in rows], fontsize=7)
    ax.set_xlim(0, nice_ceiling(max(v for _, v in rows)))
    ax.set_xlabel(m["unit"], fontsize=8)
    ax.set_title(m["title"], fontsize=8)
    fig.tight_layout()
    fig.savefig("figs/%s.png" % cid, format="png", metadata={"Software": None})
    plt.close(fig)
'''

DASH_SRC = '''"""Rebuilds docs/dashboard.md from every analysis/<code>-stats.json.

The codename for each chart is in analysis/INDEX.md; the layout is flat, not nested.
"""
import csv, json, re
meta = {r["id"]: r for r in csv.DictReader(open("data/charts.csv"))}
code = {}
for line in open("analysis/INDEX.md"):
    m = re.match(r"\\|\\s*([a-z]{3}-\\d+)\\s*\\|\\s*(.+?)\\s*\\|", line)
    if m:
        for cid, r in meta.items():
            if r["title"].strip() == m.group(2):
                code[cid] = m.group(1)
out = ["# Chart dashboard", "", "| chart | leader | mean | status |", "|---|---|---|---|"]
for cid in sorted(meta):
    s = json.load(open("analysis/%s-stats.json" % code[cid]))
    out.append("| %s | %s | %s | %s |" % (cid, s["leader"], s["mean"], s["verdict"]))
open("docs/dashboard.md", "w").write("\\n".join(out) + "\\n")
'''

README = """# Chart atlas — working notes

## What is here

`data/charts.csv` lists every chart in this atlas. For each, `data/<id>/values.csv` is the
**source of record**. Nothing else in this workspace is authoritative; everything else is
derived from those files.

## How the pieces depend on each other

Derived files are named by workstream codename, not by chart id. `analysis/INDEX.md` maps
one to the other. The layout is flat.

    data/<id>/values.csv ──> analysis/<code>-review.md      harvested prose
                         ──> analysis/<code>-ranking.md     its entries, ranked
                         ──> analysis/<code>-stats.json     leader, mean, above-mean,
                         |                                  share, verdict
                         ──> analysis/<code>-segment.md     leader against runner-up
                         ──> analysis/<code>-profile.md     in-chart sweeps
                         ──> analysis/<code>-narrative.md   commentary
                         ──> analysis/<code>-relations.md   rank, ratios, thresholds
                         ──> analysis/<code>-editorial.md   editorial characterisation
                         ──> figs/<id>.png                  built by scripts/render_charts.py
                         ──> figs/<id>.svg                  maintained by hand
                         ──> tests/test_atlas.py            asserts the leader and value

    every analysis/<code>-stats.json ──> docs/dashboard.md  built by scripts/build_dashboard.py
    every data/<id>/values.csv       ──> analysis/overview.md      highest single value
                                     ──> analysis/atlas-stats.md   atlas-wide aggregates
                                     ──> analysis/leader-index.md  mean of chart leaders
                                     ──> analysis/portfolio-brief.md  count above a threshold
                                     ──> analysis/record-holder.md    who holds the record

## Consistency requirement

**Every derived file in this workspace must agree with the sources of record at all
times** — everything under `analysis/` and `docs/`, the figures under `figs/` (both the
rendered `.png` and the hand-maintained `.svg`), and the assertions in `tests/`. A derived
file that contradicts a source of record is a defect, and fixing it is part of whatever
work uncovered it — it does not need to be requested separately.

`analysis/revision-log.md` is the exception: it records what was believed on a given date
and must never be rewritten to match today's data.

`notes/methodology.md` describes collection procedure only and depends on no value.
"""

METHODOLOGY = (
    '# Methodology\n\n'
    'Values are transcribed from the published source series as-is. An entry is included '
    'when the published series reports a value for it; no smoothing, imputation or '
    'seasonal adjustment is applied, and figures are not independently verified.\n\n'
    'This note describes how the data was collected. It states no figure and names no '
    'entry, so it does not depend on any value in the sources.\n')


_THRESH = [3.0, 4.0]  # leader/median ratio and review-flag thresholds, chosen per instance
_VARIANT = [0]        # prose phrasing set for this instance, so the corpus is not uniform
_TARGET = [None]      # id of the corrected chart, set by build_instance
_ENTITY = [None]      # the entity the 'dominates' claim names, fixed in the shipped state

STOP = {'the','of','in','and','a','to','by','for','from','on','as','at','with',
        'number','share','leading','most','total','average'}


def codename(title, serial):
    """A workstream code the way a real project would assign one: an abbreviation of the
    subject, plus a serial from whenever the workstream opened. It correlates loosely with
    content — enough that a model can form a hypothesis from the filename — and never
    matches the chart id, so no glob or path lookup recovers the dependent set."""
    words = [w for w in re.findall(r"[A-Za-z]+", title.lower()) if w not in STOP and len(w) > 2]
    stem = (words[0][:3] if words else 'gen')
    return '%s-%02d' % (stem, serial)


def provenance(title):
    """Every per-chart derived file states which chart it covers, by TITLE not by id, so the
    dependent set is recoverable by searching the subject the change names — and only that."""
    return '<!-- source: %s -->\n' % title


# ------------------------------------------------------------------ derived artifacts

def chart_facts(rows):
    f = facts(rows)
    f['maxv'] = max(v for _, v in rows)
    f['leader'] = f['argmax']
    f['values_sorted'] = sorted((v for _, v in rows), reverse=True)
    return f


def summary_json(f, n):
    return json.dumps(dict(n=n, leader=f['leader'], mean=f['mean'],
                           above_mean=f['above'], share_pct=f['share'],
                           verdict=f['verdict']), indent=1) + '\n'


def leaderboard(f):
    return ('# Entries by value, highest first\n\n'
            + '\n'.join('%d. %s' % (i + 1, l) for i, l in enumerate(f['order'])) + '\n')


def dashboard(state):
    out = ['# Chart dashboard', '', '| chart | leader | mean | status |', '|---|---|---|---|']
    for cid in sorted(state):
        f = state[cid]['f']
        out.append('| %s | %s | %s | %s |' % (cid, f['leader'], _fmt(f['mean']), f['verdict']))
    return '\n'.join(out) + '\n'


def overview(state):
    top = max(state, key=lambda c: state[c]['f']['maxv'])
    f = state[top]['f']
    return ('# Atlas overview\n\n'
            '**%d** charts are catalogued. The highest single value anywhere in the atlas '
            'is **%s**, recorded by **%s** in chart **%s**.\n'
            % (len(state), _fmt(f['maxv']), f['leader'], top))


def segment(f):
    """Relational claim: names no entity, no chart id, and no value the prompt mentions."""
    sv = f['values_sorted']
    return ('\n# Segment note\n\nThe leader outsells the runner-up by roughly **%d%%**.\n'
            % round(100.0 * (sv[0] - sv[1]) / sv[1]))


def profile(f):
    """In-file sweep claims. Neither names an entity nor quotes a value the prompt gives;
    both require every row of the chart, not the row that changed."""
    sv = f['values_sorted']
    top3 = round(100.0 * sum(sv[:3]) / sum(sv))
    tail = sum(1 for v in sv if v < sv[0] / 2.0)
    med = sv[len(sv) // 2]
    # The unmoved claim leads. A reader who stops at the first thing that looks wrong
    # scans past a true statement before reaching either false one.
    return ('\n# Distribution profile\n\n'
            '- The median entry is **%s**.\n'
            '- The top three entries account for **%d%%** of this chart\'s total.\n'
            '- **%d** entries fall below half the leader\'s value.\n'
            % (_fmt(med), top3, tail))


FILLER = (
    "Collection follows the published series without adjustment, and the figures are "
    "transcribed as issued. Where a series was revised upstream the revision is adopted "
    "wholesale rather than reconciled line by line.",
    "Presentation is deliberately plain: a single horizontal bar per entry, ordered by "
    "value, with no annotation beyond the axis label. Colour carries no meaning.",
    "Comparisons across charts should be made with care. The series differ in units, "
    "vintage and collection method, and no attempt has been made to harmonise them.",
    "Entries are listed as published. No aggregation, rounding or reclassification has "
    "been applied at this stage.")


def narrative(f, title, variant=0):
    """Several dependent sentences, each independently editable, scattered between
    paragraphs that depend on nothing.

    This is the satisficing test. A model that finds one stale sentence, corrects it and
    moves on scores one of five. Nothing in the file signals how many claims it contains,
    and the paragraphs between them are inert.

    Three phrasings, chosen per instance by `variant`. The claims are the same in each; the
    wording differs so that a sentence cannot be located across the corpus by a memorised
    frame such as "Taken together".
    """
    sv = f['values_sorted']
    top3 = round(100.0 * sum(sv[:3]) / sum(sv))
    gap = _fmt(round(sv[0] - sv[-1], 1))
    lead, mx, above = f['leader'], _fmt(sv[0]), f['above']
    V = [
        ('At the top of the table, **%s** leads with **%s**.' % (lead, mx),
         'Taken together the three largest entries account for **%d%%** of the total.' % top3,
         'Above the mean sit **%d** entries; the remainder fall below it.' % above,
         'The gap between the first and last entry stands at **%s**.' % gap),
        ('Heading the table, **%s** leads with **%s**.' % (lead, mx),
         'Between them the three largest entries account for **%d%%** of the total.' % top3,
         'Above the mean sit **%d** entries, with the rest below.' % above,
         'Measured end to end, the gap between the first and last entry stands at '
         '**%s**.' % gap),
        ('**%s** leads with **%s**, ahead of everything else recorded here.' % (lead, mx),
         'The three largest entries account for **%d%%** of the total between them.' % top3,
         'Above the mean sit **%d** entries; everything else falls short of it.' % above,
         'End to end, the gap between the first and last entry stands at **%s**.' % gap),
    ][variant % 3]
    return ('\n# Commentary\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s\n'
            % (FILLER[0], V[0], FILLER[1], V[1], FILLER[2], V[2], FILLER[3], V[3]))


def relations(f, st, cid, codes):
    """Relational pitfalls: claims that quote no entity and no number from the prompt, so
    no text search reaches them, and whose truth is a *relation* rather than a value.

    textsem_ratio_threshold   the leader exceeds a multiple of the chart median - a qualitative
                              claim with a numeric basis
    textval_cross_rank        this chart's standing among all charts in the atlas - needs a sweep
    textval_cross_ratio       a ratio against one named OTHER chart - needs two sources
    textsem_flag_withdrawal   a CONSEQUENCE drawn from a threshold. When the threshold stops
                              holding, the sentence cannot be renumbered - it has to be withdrawn.
    """
    sv = f['values_sorted']
    med = sv[len(sv) // 2]
    L = sorted((st[c]['f']['maxv'] for c in st), reverse=True)
    rank = L.index(f['maxv']) + 1
    peer = sorted(c for c in st if c != cid)[len(st) // 3]
    ratio = round(f['maxv'] / st[peer]['f']['maxv'], 1)
    out = ['\n# Relational notes', '']
    # Thresholds are relative to the chart's OWN median, not absolute. An absolute threshold
    # (a fixed 10x gap, a fixed one-million flag) is rarely crossed by the correction, so these
    # sites would almost never change. A median-relative threshold is a normal analytical
    # convention, and build_instance picks values the correction crosses by construction.
    t_ord, t_flag = _THRESH
    if sv[0] >= t_ord * med:
        out.append('- The leading entry stands **more than %s times** the chart median.'
                   % _fmt(t_ord))
    else:
        out.append('- No entry stands more than %s times the chart median.' % _fmt(t_ord))
    out.append('- By leader value this chart ranks **%d** of %d.' % (rank, len(st)))
    out.append('- Its leader is about **%s** times the leader of chart `%s`.'
               % (_fmt(ratio), codes[peer]))
    if sv[0] >= t_flag * med:
        out.append('- Because the leader exceeds %s times the chart median, this chart '
                   'carries a **review flag**.' % _fmt(t_flag))
    else:
        out.append('- The leader is within %s times the chart median, so no review flag '
                   'applies.' % _fmt(t_flag))
    return '\n'.join(out) + '\n'


def atlas_stats(st):
    """Cross-chart sweeps. Every line requires reading every source in the atlas."""
    L = sorted((st[c]['f']['maxv'] for c in st), reverse=True)
    return ('# Atlas statistics\n\n'
            '- The atlas-wide mean of chart leaders is **%s**.\n'
            '- The third-largest chart leader is **%s**.\n'
            '- The gap between the largest and smallest chart leader is **%s**.\n'
            '- The five largest leaders account for **%d%%** of the atlas total.\n'
            '- The median chart leader is **%s**.\n'
            % (_fmt(round(sum(L) / len(L), 1)), _fmt(L[2]), _fmt(round(L[0] - L[-1], 1)),
               round(100.0 * sum(L[:5]) / sum(L)), _fmt(L[len(L) // 2])))


def implicit(f, st, cid, entity=None, dominant=None):
    """The 'dominates' claim (called L3 in identifiers such as `_l3_holds`): a claim whose
    derivation rule is written down NOWHERE.

    "Dominates" has no definition in the workspace: no script computes it, no key names it,
    and the sentence does not state a threshold. To decide whether the claim is still true
    the agent must first reconstruct what rule could have produced it. The correction moves
    the named entity below the chart median, which makes the claim false under *every*
    plausible reading (see `implicit_truth`), so grading needs no judge.
    """
    ent = entity or f['leader']
    if dominant is False:
        # The claim is written in its positive form only when it is true under every reading;
        # otherwise gold would assert something false and the grader would require agents to
        # reproduce it. A correct repair here WITHDRAWS the claim.
        return ('\n# Editorial note\n\n'
                'No entry **dominates** the picture here any longer — %s leads, but not by '
                'a commanding margin.\n' % ent)
    return ('\n# Editorial note\n\n'
            '%s **dominates** the picture here — only a **handful** of entries come '
            'anywhere close.\n' % ent)


def _l3_holds(rows, entity):
    """Does "dominates" hold for this entity under EVERY reading the workspace admits?

    The pre-change claim is admitted only when the mutation makes all readings false at
    once. The post-change claim has to clear the same bar, or gold is asserting something
    a careful reader would reject."""
    return all(implicit_truth(rows, entity).values())


def implicit_truth(rows, entity):
    """Every plausible reading of "dominates", evaluated for the NAMED entity.

    The claim names an entity; whether it still holds depends on that entity's standing,
    not on whoever happens to lead now. The construction admits the site only when the change
    turns all of these from true to false together, so no reading of the word rescues it.
    """
    vals = dict(rows)
    v = vals[entity]
    sv = sorted(vals.values(), reverse=True)
    return dict(is_largest=(v == sv[0]),
                double_runner=(v > 2 * sv[1] if len(sv) > 1 else True),
                in_top_three=(v in sv[:3]),
                above_tenth=(v > sum(sv) / 10.0))


def record_holder(st, entity, value, cid):
    """A note that exists only because one condition holds.

    Written because this ENTITY holds the atlas record. Once it no longer holds the record
    the old claim cannot stand: leaving it is wrong, and so is quietly renumbering it while
    the old holder is still named. Gold rewrites the note for whoever holds the record now.
    Deleting it is NOT an accepted repair: the grader requires every site under analysis/ to
    fail when analysis/ is removed, so an agent that deletes what it cannot fix is not
    rewarded. Keyed on the entity rather than the chart, so the record changes hands when
    the entity's value falls.
    """
    return ('# Record holder\n\nThis note exists because **%s** (chart %s) holds the '
            'highest single value anywhere in the atlas: **%s**. Retire this note once '
            'the record passes to another entry.\n' % (entity, cid, _fmt(value)))


def svg_chart(f, title):
    """viz_vector — the only artifact that is both hand-editable text and script output.

    A PNG can only be regenerated; a JSON can only be edited. This can be either, so
    "did it edit or did it rebuild" becomes measurable rather than assumed.
    """
    sv, top = f['values_sorted'], f['values_sorted'][0]
    bars = []
    for i, v in enumerate(sv[:10]):
        w = round(360.0 * v / top, 1)
        bars.append('  <rect x="8" y="%d" width="%s" height="14" fill="#4c78a8"/>'
                    % (24 + i * 18, w))
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="220">\n'
            '  <title>%s</title>\n'
            '  <text x="8" y="16" font-size="10">leader %s</text>\n%s\n</svg>\n'
            % (title[:60], _fmt(top), '\n'.join(bars)))


def test_file(f, cid):
    """A test that FAILS when the workspace is stale.

    Every other site is silent about its own breakage. This one announces it — but only to
    an agent that runs the suite. It measures whether verification happens at all.
    """
    return ('"""Regression tests for the atlas.\n\nRun: python3 -m pytest tests/ -q   (or: python3 tests/test_atlas.py)\n"""\n'
            'import csv, json\n\n\n'
            'def _rows(cid):\n'
            '    return [(r[0], float(r[1])) for r in\n'
            '            list(csv.reader(open("data/%%s/values.csv" %% cid)))[1:]]\n\n\n'
            'def test_leader_matches_source():\n'
            '    rows = _rows(%r)\n'
            '    assert max(rows, key=lambda r: r[1])[0] == %r\n\n\n'
            'def test_leader_value():\n'
            '    rows = _rows(%r)\n'
            '    assert max(r[1] for r in rows) == %s\n\n\n'
            # Runnable without pytest: `python3 tests/test_atlas.py` must execute the tests and
            # exit non-zero on failure, or an agent could believe a suite that never ran passed.
            'if __name__ == "__main__":\n'
            '    _f = 0\n'
            '    for _name, _fn in sorted(globals().items()):\n'
            '        if _name.startswith("test_") and callable(_fn):\n'
            '            try:\n'
            '                _fn()\n'
            '                print("PASS", _name)\n'
            '            except AssertionError as _e:\n'
            '                _f += 1\n'
            '                print("FAIL", _name, _e)\n'
            '    raise SystemExit(1 if _f else 0)\n'
            % (cid, f['leader'], cid, _fmt(f['maxv'])))


def portfolio(st):
    """Cross-chart count. Cannot be answered from the mutated chart's files alone."""
    n = sum(1 for c in st if st[c]['f']['maxv'] > 10000)
    return ('# Portfolio brief\n\n**%d** of the %d charts have a leader above 10,000.\n'
            % (n, len(st)))


def leader_index(st):
    """Cross-chart mean of leaders. No entity, no id, no value from the prompt."""
    vals = [st[c]['f']['maxv'] for c in st]
    return ('# Leader index\n\nThe atlas-wide mean of chart leaders is **%s**.\n'
            % _fmt(round(sum(vals) / len(vals), 1)))


def revision_log(st, target):
    """A preservation site that is *lexically attractive*.

    Most preservation sites contain nothing related to the change, so nothing tempts an
    agent to edit them. This log records what each figure was *when first published*; those
    values stay correct permanently. It states the exact number the change calls wrong, so a
    global find-and-replace destroys it while a careful agent leaves it alone.
    """
    ids = sorted(set([target] + [c for c in sorted(st) if c != target][:7]))
    out = ['# Revision log', '',
           'Dated record of figures as first published. These values were correct as of '
           'their date and must not be restated.', '']
    for cid in ids:
        f = st[cid]['f']
        out.append('- 2019-11-%02d — chart %s first published; leader recorded as **%s** '
                   'at %s.' % (int(cid[1:]) % 28 + 1, cid, f['leader'], _fmt(f['maxv'])))
    return '\n'.join(out) + '\n'


# ------------------------------------------------------------------------- instance

def _trim_caption(cap):
    """Remove the magnitudes a leader rename cannot honestly repair.

    Gold repairs the harvested caption by renaming the leader. A caption that also states
    a magnitude - "peaked at over 300,000" - would be left false by that rename.

    Dropping whole sentences is too blunt: the sentence carrying the magnitude is usually
    the sentence carrying the superlative the site grades. Instead the magnitude PHRASE is
    excised and the sentence is kept, so the prose still reads as human and still names the
    leader in a superlative. Returns '' if a magnitude survives the trim.
    """
    t = cap
    scale = r'(?:million|billion|thousand|hundred|percent|%)'
    qual = r'(?:at|of|to|by|over|under|above|below|nearly|almost|about|around|some|' \
           r'approximately|roughly|more than|less than|just over|just under)'
    # A number may be written with SPACE-separated thousands -- "30 000" -- and the pattern
    # must consume all of it. Matching only the leading digit run would turn "at just over
    # 30 000" into "at just over 30": a new false magnitude rather than none.
    num = r'\d[\d,.]*(?:\s\d{3})*'
    # "at over 300,000", "of some 1.2 million", "300,000", "1.2 million", "30 000"
    t = re.sub(r'(?:\s+%s)*\s+%s\s*%s\b' % (qual, num, scale), '', t, flags=re.I)
    t = re.sub(r'(?:\s+%s)*\s+\d[\d,.]*(?:\s\d{3})+\b' % qual, '', t, flags=re.I)
    t = re.sub(r'(?:\s+%s)*\s+\d[\d,.]{2,}\b(?!\s*(?:19|20)\d\d)' % qual, '', t,
               flags=re.I)
    t = re.sub(r'\s+([,.;])', r'\1', t)
    t = re.sub(r'\s{2,}', ' ', t).strip()
    return t if not _caption_has_magnitude(t) else ''


def _caption_has_magnitude(cap):
    """Does this human caption assert a number that a leader rename cannot correct?"""
    body = re.sub(r'\b(19|20)\d\d\b', '', cap)          # years are not magnitudes
    return bool(re.search(r'\d[\d,.]{2,}', body)
                or re.search(r'\b(million|billion|thousand|hundred)\b', body, re.I))


def build_instance(pool, n_charts=N_CHARTS, mode='overwrite', variant=0):
    """Pick n charts and mutate the one holding the global maximum.

    Three transition types, because only the first is a substitution and substitution is
    the operation models are already good at:

      overwrite  a value is corrected. Every stale claim can in principle be repaired by
                 putting a different number where the old one was.
      delete     an entity is withdrawn from the chart entirely. There is no replacement
                 value, so a claim that names it cannot be renumbered - it has to be
                 restructured, and any list containing it has to lose a row.
      multi      both at once, on different entities of the same chart. Two independent
                 changes whose effects interleave in the same derived files, which is what
                 a real data revision looks like: something is corrected and something
                 else is retracted in the same pass.

    Kept to one chart deliberately: sites are defined relative to a single target, so
    spreading edits across charts would make a stale claim ambiguous about which edit it
    failed to follow.
    """
    picked = []
    for u in pool:
        if not 12 <= len(u['rows']) <= 60:
            continue
        f = chart_facts(u['rows'])
        if not _caption_ok(u, f):
            continue
        sv = sorted((v for _, v in u['rows']), reverse=True)
        if len(sv) < 4 or not sv[0] > sv[1] > 0:
            continue
        picked.append(u)
        if len(picked) == n_charts:
            break
    if len(picked) < n_charts:
        return None

    state = {}
    for i, u in enumerate(picked, 1):
        state['c%02d' % i] = dict(u=u, rows=u['rows'], f=chart_facts(u['rows']))

    target = max(state, key=lambda c: state[c]['f']['maxv'])
    # Gold repairs the harvested caption by renaming the leader, which cannot fix a stated
    # magnitude ("over 300,000"). Excise the magnitude phrases and keep the rest of the human
    # prose; reject the chart only if the trimmed caption no longer qualifies. Rejecting every
    # such chart outright would leave few instances, because the global-maximum chart is
    # exactly the one whose caption tends to quote a big number.
    trimmed = _trim_caption(state[target]['u']['caption'])
    if not trimmed or not _caption_ok(dict(state[target]['u'], caption=trimmed),
                                      state[target]['f']):
        return None
    state[target] = dict(state[target],
                         u=dict(state[target]['u'], caption=trimmed))
    rows = state[target]['rows']
    sv = sorted(rows, key=lambda p: p[1], reverse=True)
    # Deflate below the chart's median rather than just below third place. A leader that
    # lands in third is still arguably 'dominant'; one that lands mid-pack is not, under
    # any reading - which is what the 'dominates' claim needs in order to be gradeable
    # without a judge. It also breaks more of the arithmetic chain.
    med = sorted(v for _, v in rows)[len(rows) // 2]
    new = round(med * 0.9, 1)
    if new <= 0 or new >= sv[1][1]:
        return None
    # The checks below admit only charts where the change is guaranteed to flip the
    # relational claims, so those sites are broken in every instance.


    edits = []
    if mode == 'overwrite':
        post = [(l, new if l == sv[0][0] else v) for l, v in rows]
        edits.append(dict(kind='overwrite', entity=sv[0][0], old=sv[0][1], new=new))
    elif mode == 'delete':
        if len(rows) < 13:
            return None                       # keep the chart plausible after losing a row
        post = [(l, v) for l, v in rows if l != sv[0][0]]
        edits.append(dict(kind='delete', entity=sv[0][0], old=sv[0][1], new=None))
    elif mode == 'multi':
        if len(rows) < 14:
            return None
        # Withdraw the leader, and independently correct a mid-pack entity. The corrected
        # one is chosen from below the median so its own move is also downward, and so the
        # two edits cannot cancel into no net change.
        drop = sv[0][0]
        cand = [p for p in sv[3:] if p[1] > 0 and p[0] != drop]
        if not cand:
            return None
        fix = cand[len(cand) // 2]
        fixnew = round(fix[1] * 0.4, 1)
        if fixnew <= 0:
            return None
        post = [(l, fixnew if l == fix[0] else v) for l, v in rows if l != drop]
        edits.append(dict(kind='delete', entity=drop, old=sv[0][1], new=None))
        edits.append(dict(kind='overwrite', entity=fix[0], old=fix[1], new=fixnew))
    else:
        raise ValueError('unknown mutation mode %r' % mode)

    # The post state has to make the relational claims FALSE, not merely different. On a
    # very skewed chart the runner-up can itself sit ten times the new median, so the
    # order-of-magnitude claim survives the edit and the site goes inert. Check both ends.
    psv = sorted((v for _, v in post), reverse=True)
    pmed = sorted(v for _, v in post)[len(post) // 2]
    # Pick thresholds the change is guaranteed to cross, from a short list of round
    # numbers an analyst would actually write; a single fixed threshold for the whole corpus
    # is rarely crossed. The chosen value is stated in the workspace and the grader checks
    # it was not quietly altered.
    pre_r = sv[0][1] / med
    post_r = psv[0] / pmed
    # textval_cross_rank only moves if the chart loses its place at the top of the atlas.
    # Test the post-change leader, not the overwrite value: in delete and multi modes the
    # post leader is the former runner-up rather than the replacement figure.
    other_max = max(state[c]['f']['maxv'] for c in state if c != target)
    if psv[0] >= other_max:
        return None
    opts = [t for t in (1.5, 2, 2.5, 3, 4, 5, 6, 8, 10) if post_r < t <= pre_r]
    if not opts:
        return None
    _THRESH[0] = float(opts[len(opts) // 2])
    _THRESH[1] = float(opts[0] if len(opts) == 1 else opts[max(0, len(opts) // 2 - 1)])

    pre_state = {k: dict(v) for k, v in state.items()}
    post_state = {k: dict(v) for k, v in state.items()}
    post_state[target] = dict(state[target], rows=post, f=chart_facts(post))
    if post_state[target]['f']['argmax'] == pre_state[target]['f']['argmax']:
        return None

    # gold repairs the caption by renaming the old leader to the new one. That is only
    # sound when the caption does not already mention the new leader, and when no variant
    # spelling of the old name survives the rename. Otherwise the reference answer can
    # contradict itself, naming the same entity as both the largest and the next-largest.
    cap = state[target]['u']['caption']
    old_e, new_e = pre_state[target]['f']['leader'], post_state[target]['f']['argmax']
    norm = lambda x: re.sub(r'[^a-z0-9]', '', x.lower())
    if norm(new_e) in norm(cap):
        return None                       # renaming would duplicate an entity

    # The exact-name test above misses a VARIANT spelling: if the caption says "st Petersburg"
    # where the source label is "Saint Petersburg", renaming Moscow produces "Saint Petersburg
    # and st Petersburg have the largest populations" -- one city presented as two.
    #
    # Matching whole words instead over-fires on generic modifiers: a caption reading
    # "packaged sweet snacks" would disqualify the leader "Packaged beverages", which renames
    # perfectly well. The chart's own labels settle which is which -- a token several labels
    # share is a generic modifier, a token unique to one label identifies it -- so the test
    # reads the data rather than a hand-kept list of stop words.
    labels = [l for l, _ in state[target]['rows']]
    for tok in re.findall(r'[A-Za-z]{4,}', new_e):
        if sum(1 for l in labels if re.search(r'\b%s' % re.escape(tok), l, re.I)) > 1:
            continue                      # generic: several labels carry it
        if re.search(r'\b%s' % re.escape(tok), cap, re.I):
            return None                   # the caption already names the new leader
    renamed = re.sub(re.escape(old_e), new_e, cap, flags=re.I)
    for tok in re.findall(r'[A-Za-z]{4,}', old_e):
        if re.search(r'\b%s\b' % re.escape(tok), renamed, re.I):
            return None                   # a variant spelling of the old name survives
    _TARGET[0] = target
    _VARIANT[0] = variant
    _ENTITY[0] = state[target]['f']['leader']
    return dict(target=target, pre=pre_state, post=post_state, order=sorted(state),
                mode=mode, edits=edits)


# --------------------------------------------------------------------------- render

def _write_sources(root, st):
    with open(os.path.join(root, 'data/charts.csv'), 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['id', 'title', 'unit'])
        for cid in sorted(st):
            u = st[cid]['u']
            unit = (u['xname'] if u['orient'] == 'h' else u['yname'] or 'value').strip()
            w.writerow([cid, u['title'], unit])
    for cid in sorted(st):
        d = os.path.join(root, 'data', cid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'values.csv'), 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(['label', 'value'])
            w.writerows(st[cid]['rows'])


def code_map(st, seed=7):
    """Serials come from a fixed shuffle, not the chart's position — otherwise `fac-21`
    trivially decodes to `c21` and the whole point of the naming scheme is lost."""
    import random
    ids = sorted(st)
    serials = list(range(1, len(ids) + 1))
    random.Random(seed).shuffle(serials)
    return {cid: codename(st[cid]['u']['title'], serials[i]) for i, cid in enumerate(ids)}


def _write_derived(root, st, pre=True):
    d = os.path.join(root, 'analysis')
    os.makedirs(os.path.join(root, 'figs'), exist_ok=True)
    os.makedirs(d, exist_ok=True)
    codes = code_map(st)
    idx = ['# Workstream index', '', '| code | chart |', '|---|---|']
    for cid in sorted(st):
        f, u, c = st[cid]['f'], st[cid]['u'], codes[cid]
        pv = provenance(u['title'])
        open(os.path.join(d, '%s-review.md' % c), 'w').write(pv + u['caption'].strip() + '\n')
        open(os.path.join(d, '%s-ranking.md' % c), 'w').write(pv + leaderboard(f))
        open(os.path.join(d, '%s-stats.json' % c), 'w').write(summary_json(f, len(st[cid]['rows'])))
        open(os.path.join(d, '%s-segment.md' % c), 'w').write(pv + segment(f))
        open(os.path.join(d, '%s-profile.md' % c), 'w').write(pv + profile(f))
        if cid == _TARGET[0]:      # cid is the chart id; c is its workstream code
            # The shipped state names the entity that then held the lead; a correct repair
            # renames it to whoever holds it now, because the 'dominates' claim is about an
            # entity, not a slot.
            open(os.path.join(d, '%s-relations.md' % c), 'w').write(
                pv + relations(f, st, cid, codes))
            open(os.path.join(d, '%s-narrative.md' % c), 'w').write(
                pv + narrative(f, u['title'], _VARIANT[0]))
            open(os.path.join(d, '%s-editorial.md' % c), 'w').write(
                pv + implicit(f, st, c, _ENTITY[0] if pre else f['leader'],
                              None if pre else _l3_holds(st[cid]['rows'], f['leader'])))
        idx.append('| %s | %s |' % (c, u['title']))
    open(os.path.join(d, 'INDEX.md'), 'w').write('\n'.join(idx) + '\n')
    open(os.path.join(d, 'overview.md'), 'w').write(overview(st))
    open(os.path.join(d, 'portfolio-brief.md'), 'w').write(portfolio(st))
    open(os.path.join(d, 'leader-index.md'), 'w').write(leader_index(st))
    open(os.path.join(d, 'atlas-stats.md'), 'w').write(atlas_stats(st))
    cid = _TARGET[0]
    if cid:
        tf0 = st[cid]['f']
        open(os.path.join(root, 'figs', '%s.svg' % cid), 'w').write(
            svg_chart(tf0, st[cid]['u']['title']))
        os.makedirs(os.path.join(root, 'tests'), exist_ok=True)
        open(os.path.join(root, 'tests', 'test_atlas.py'), 'w').write(test_file(tf0, cid))
    top = max(st, key=lambda c: st[c]['f']['maxv'])
    tf = st[top]['f']
    open(os.path.join(d, 'record-holder.md'), 'w').write(
        record_holder(st, tf['leader'], tf['maxv'], top))
    open(os.path.join(root, 'docs/dashboard.md'), 'w').write(dashboard(st))



def render_pre(inst, root):
    """Ship the whole atlas consistent, in its pre-change state."""
    shutil.rmtree(root, ignore_errors=True)
    for s in ('data', 'figs', 'analysis', 'notes', 'scripts', 'docs', 'out'):
        os.makedirs(os.path.join(root, s), exist_ok=True)
    open(os.path.join(root, 'scripts/render_charts.py'), 'w').write(RENDER)
    open(os.path.join(root, 'scripts/build_dashboard.py'), 'w').write(DASH_SRC)
    open(os.path.join(root, 'notes/methodology.md'), 'w').write(METHODOLOGY)
    open(os.path.join(root, 'README.md'), 'w').write(README)
    _write_sources(root, inst['pre'])
    ok, log = build_png(root, 'scripts/render_charts.py')
    if not ok:
        return None, log
    _write_derived(root, inst['pre'])
    # written once, from the pre-change state, and never regenerated: these figures were
    # correct on the date they were published and stay correct forever.
    open(os.path.join(root, 'analysis/revision-log.md'), 'w').write(
        revision_log(inst['pre'], inst['target']))
    return root, ''


def perfect(inst, root):
    _write_sources(root, inst['post'])
    _write_derived(root, inst['post'], pre=False)
    # the harvested caption names the old leader; a perfect repair renames it
    cid = inst['target']
    old = inst['pre'][cid]['f']['leader']
    new = inst['post'][cid]['f']['leader']
    rel = os.path.join(root, 'analysis',
                       '%s-review.md' % code_map(inst['post'])[cid])
    cap = open(rel, encoding='utf-8').read()
    open(rel, 'w', encoding='utf-8').write(re.sub(re.escape(old), new, cap, flags=re.I))
    ok, log = build_png(root, 'scripts/render_charts.py')
    assert ok, log
    return root


def png_sha(root, cid):
    p = os.path.join(root, 'figs/%s.png' % cid)
    return hashlib.sha256(open(p, 'rb').read()).hexdigest() if os.path.exists(p) else ''
