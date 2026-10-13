"""Deterministic grader for atlas workspaces. Pure code, no LLM judge.

A workspace holds tens of charts and a few hundred files; the correction changes one source
cell. Sites split three ways:

  BROKEN     the mutated chart's derived layer plus the cross-chart aggregates that move.
  NULL-LIVE  claims that look like they should move and do not - the portfolio count, and
             the revision log, which is *lexically attractive*: it states the exact number
             the change calls wrong, so a global find-and-replace destroys it.
  NULL-BULK  every other chart's files, graded on claim validity, never on bytes. Byte
             identity would penalise legitimate edits such as tie reorderings, typo fixes
             or a faithful redraw.
"""
import sys, os, re, csv, json, hashlib, subprocess, shutil, tempfile, math
import gen_vis_atlas as A

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from gen_vis import _fmt, SUP_W

DEPTH = {'textsem_superlative': 1, 'list_ranking': 1, 'json_leader': 1, 'json_mean': 1, 'json_above_mean': 2, 'json_share': 3,
         'json_verdict': 4, 'textval_leader_margin': 2, 'textval_atlas_dashboard': 5, 'textval_atlas_overview': 2, 'textval_atlas_leader_index': 2,
         'viz_raster': 3, 'textval_atlas_portfolio': 2, 'control_revision_log': 0}
PATTERN = {'textsem_superlative': 'status-flip', 'list_ranking': 'substitution', 'json_leader': 'status-flip',
           'json_mean': 'arithmetic', 'json_above_mean': 'arithmetic', 'json_share': 'arithmetic',
           'json_verdict': 'threshold', 'textval_leader_margin': 'relational', 'textval_atlas_dashboard': 'join',
           'textval_atlas_overview': 'join', 'textval_atlas_leader_index': 'join', 'viz_raster': 'regenerate',
           'textval_atlas_portfolio': 'join', 'control_revision_log': 'historical'}
# findable by searching for something the change instruction actually says?
REACH = {'textsem_superlative': 'named', 'list_ranking': 'named', 'json_leader': 'named', 'json_mean': 'named',
         'json_above_mean': 'named', 'json_share': 'named', 'json_verdict': 'named', 'textval_atlas_dashboard': 'named',
         'textval_atlas_overview': 'named', 'viz_raster': 'named',
         'textval_leader_margin': 'nameless', 'textval_atlas_leader_index': 'nameless', 'textval_atlas_portfolio': 'nameless',
         'control_revision_log': 'named'}

# Five claims scattered through one prose file, each independently editable. This is the
# satisficing probe: a model that corrects the first stale sentence and moves on scores 1/5.
# The generator varies the wording per instance so the corpus does not share a single set
# of sentence frames; the claim each sentence carries is identical, so the grader accepts
# whichever phrasing the fixture used.
NARR = {
    'textval_narr_leader': r'leads with',
    'textval_narr_value':  r'leads with \*\*([\d,.]+)\*\*',
    'textval_narr_top3':   r'three largest entries account for \*\*(\d+)%\*\*',
    'textval_narr_above':  r'Above the mean sit \*\*(\d+)\*\*',
    'textval_narr_gap':    r'gap between the first and last entry stands at \*\*([\d,.]+)\*\*',
}
for _s in NARR:
    DEPTH[_s], PATTERN[_s], REACH[_s] = 2, 'prose-scattered', 'nameless'
REACH['textval_narr_leader'] = REACH['textval_narr_value'] = 'named'

REL = ('textsem_ratio_threshold', 'textval_cross_rank', 'textval_cross_ratio', 'textsem_flag_withdrawal')
for _s in REL:
    DEPTH[_s], PATTERN[_s], REACH[_s] = 2, 'relational', 'nameless'
PATTERN['textsem_flag_withdrawal'] = 'consequence'

# Sweep sites: each is one bolded value on a labelled bullet. Their staleness can only be
# established by recomputing - over every row of the chart (textval_chart_*) or over every
# chart in the atlas (textval_atlas_*). Moved and unmoved claims deliberately share a file,
# so a wholesale regeneration has to get the unmoved ones right too.
SWEEP = {
    'textval_chart_top3':    ('profile', r'top three entries account for \*\*(-?[\d.]+)%\*\*'),
    'textval_chart_tail':    ('profile', r'\*\*(\d+)\*\* entries fall below half'),
    'textval_chart_median':  ('profile', r'median entry is \*\*([\d,.]+)\*\*'),
    'textval_atlas_mean':   ('atlas',   r'mean of chart leaders is \*\*([\d,.]+)\*\*'),
    'textval_atlas_third':  ('atlas',   r'third-largest chart leader is \*\*([\d,.]+)\*\*'),
    'textval_atlas_spread': ('atlas',   r'largest and smallest chart leader is \*\*([\d,.]+)\*\*'),
    'textval_atlas_concentration':   ('atlas',   r'five largest leaders account for \*\*(\d+)%\*\*'),
    'textval_atlas_median': ('atlas',   r'median chart leader is \*\*([\d,.]+)\*\*'),
}
for _s, _d, _p, _r in (('textsem_dominance', 1, 'implicit', 'named'),
                       ('textval_atlas_record_note', 2, 'retire', 'named'),
                       ('viz_vector', 3, 'regenerate-or-edit', 'named'),
                       ('exec_test', 1, 'assertion', 'named')):
    DEPTH[_s], PATTERN[_s], REACH[_s] = _d, _p, _r

for _s in SWEEP:
    DEPTH[_s] = 2 if _s.startswith('PROF') else 3
    PATTERN[_s] = 'sweep-chart' if _s.startswith('PROF') else 'sweep-atlas'
    REACH[_s] = 'nameless'


SWEEP_ANCHORS = {
    'textval_chart_top3':    [('top three', 'three largest', 'three biggest'),
                     ('account', 'make up', 'represent', 'comprise')],
    'textval_chart_tail':    ['fall below half'],
    'textval_chart_median':  [('median entry', 'median value', 'middle entry')],
    'textval_atlas_mean':   [('mean of chart leaders', 'average of chart leaders',
                      'average across chart leader', 'mean chart leader value')],
    'textval_atlas_third':  ['third-largest chart leader'],
    'textval_atlas_spread': ['largest and smallest chart leader'],
    'textval_atlas_concentration':   [('five largest leaders', 'top five leaders',
                      'five biggest leaders')],
    'textval_atlas_median': ['median chart leader'],
}
NARR_ANCHORS = {
    'textval_narr_value': ['leads with'],
    'textval_narr_top3':  [('three largest entries', 'top three entries',
                    'three biggest entries')],
    'textval_narr_above': [('above the mean', 'exceed the mean', 'over the mean')],
    'textval_narr_gap':   [('first and last entry', 'first and last', 'top and bottom entry')],
}


MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_BINARY_BYTES = 64 * 1024 * 1024


def _safe_file(root, rel, max_bytes):
    """Resolve one untrusted workspace file without following it outside the workspace."""
    if not root or not rel or os.path.isabs(rel):
        return None
    base = os.path.realpath(root)
    p = os.path.join(base, rel)
    real = os.path.realpath(p)
    try:
        if os.path.commonpath((base, real)) != base:
            return None
        if os.path.islink(p) or not os.path.isfile(real):
            return None
        if os.path.getsize(real) > max_bytes:
            return None
    except (OSError, ValueError):
        return None
    return real


def _read(root, rel):
    p = _safe_file(root, rel,
                   MAX_BINARY_BYTES if rel.endswith('.png') else MAX_TEXT_BYTES)
    if p is None:
        return None
    if rel.endswith('.png'):
        return hashlib.sha256(open(p, 'rb').read()).hexdigest()
    return open(p, encoding='utf-8', errors='replace').read()


def _json(t):
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError('duplicate JSON key: %s' % k)
            out[k] = v
        return out

    def nonfinite(value):
        raise ValueError('non-finite JSON number: %s' % value)

    try:
        return json.loads(t, object_pairs_hook=unique, parse_constant=nonfinite)
    except Exception:
        return None


def rel_for(site, code, cid):
    return {'textsem_superlative': 'analysis/%s-review.md' % code,
            'list_ranking': 'analysis/%s-ranking.md' % code,
            'textval_leader_margin': 'analysis/%s-segment.md' % code,
            'textval_atlas_dashboard': 'docs/dashboard.md',
            'textval_atlas_overview': 'analysis/overview.md',
            'textval_atlas_leader_index': 'analysis/leader-index.md',
            'textval_atlas_portfolio': 'analysis/portfolio-brief.md',
            'control_revision_log': 'analysis/revision-log.md',
            'viz_raster': 'figs/%s.png' % cid,
            'textsem_dominance': 'analysis/%s-editorial.md' % code,
            'textsem_ratio_threshold': 'analysis/%s-relations.md' % code,
            'textval_cross_rank': 'analysis/%s-relations.md' % code,
            'textval_cross_ratio': 'analysis/%s-relations.md' % code,
            'textsem_flag_withdrawal': 'analysis/%s-relations.md' % code,
            'textval_narr_leader': 'analysis/%s-narrative.md' % code,
            'textval_narr_value': 'analysis/%s-narrative.md' % code,
            'textval_narr_top3': 'analysis/%s-narrative.md' % code,
            'textval_narr_above': 'analysis/%s-narrative.md' % code,
            'textval_narr_gap': 'analysis/%s-narrative.md' % code,
            'textval_atlas_record_note': 'analysis/record-holder.md',
            'viz_vector': 'figs/%s.svg' % cid,
            'exec_test': 'tests/test_atlas.py',
            'textval_chart_top3': 'analysis/%s-profile.md' % code,
            'textval_chart_tail': 'analysis/%s-profile.md' % code,
            'textval_chart_median': 'analysis/%s-profile.md' % code,
            'textval_atlas_mean': 'analysis/atlas-stats.md',
            'textval_atlas_third': 'analysis/atlas-stats.md',
            'textval_atlas_spread': 'analysis/atlas-stats.md',
            'textval_atlas_concentration': 'analysis/atlas-stats.md',
            'textval_atlas_median': 'analysis/atlas-stats.md',
            }.get(site, 'analysis/%s-stats.json' % code)


# ---------------------------------------------------------------- locate, then compare
#
# Value sites separate two jobs: FINDING the sentence that carries the claim, and CHECKING
# the value it states. Anchors locate the claim tolerantly, so an ordinary reword ("stands
# at" for "is", emphasis dropped, clause reordered) is still found; the value is then
# compared exactly.

def _sentences(txt):
    return [x.strip() for x in re.split(r'(?<=[.!?])\s+|\n', txt or '') if x.strip()]


def _nums(s):
    # A decimal point must be followed by a digit, so the sentence-final period in
    # "leads with 478701." is not read as part of the number.
    return {x.replace(',', '') for x in re.findall(r'-?\d[\d,]*(?:\.\d+)?', s)}


def _num_eq(a, b):
    """Numeric equality, not string equality.

    123 and 123.0 are the same figure, and so are 1.3 and 1.30, so a repair that formats a
    correct value differently still passes.
    """
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a) == str(b)


def _states(line, want):
    return any(_num_eq(x, want) for x in _nums(line))


def _anchored(txt, anchors):
    """Sentences carrying the claim.

    An anchor may be a string, or a tuple of alternative phrasings any one of which
    identifies the claim - "mean of chart leaders" and "average ... chart leader" name the
    same quantity, so a correct rewording is still found.
    """
    def has(s, a):
        alts = (a,) if isinstance(a, str) else a
        return any(x.lower() in s.lower() for x in alts)
    return [s for s in _sentences(txt) if all(has(s, a) for a in anchors)]


# Words that NEGATE what follows them, as opposed to merely contrasting. The distinction
# matters: "not 999 but 2" negates 999 and asserts 2, while "999 and also 2" asserts both.
# A symmetric rule that treats any contrast between two numbers alike cannot tell which is
# claimed: it would pass "ranks 999 and also ranks 2" (a contradiction) and fail "ranks not
# 999 but 2" (a correct repair). Polarity has to be read, not just adjacency.
NEGATOR = re.compile(r'\b(?:not|no longer|never|rather than|instead of|as opposed to|'
                     r'previously|formerly|corrected from|superseded|up from|'
                     r'down from|revised from)\b', re.I)
NUMBER_RE = re.compile(r'-?\d[\d,]*(?:\.\d+)?')


def _context_number(line, start, end):
    """Numbers that identify context rather than a value asserted by the claim.

    This is deliberately a small, explicit allowance: dates and versions, chart ids,
    denominators (``2 of 30``) and bracketed citations. A nearby conjunction does not make
    two numbers rivals, so the ``and`` in ``first and last`` does not turn a leading date
    into a contradiction.
    """
    before = line[max(0, start - 32):start]
    after = line[end:end + 2]
    return bool(
        re.search(r'\b(?:as of|during|since|updated|dated|in the year|year|version)\s*$',
                  before, re.I)
        or re.search(r'(?:\bchart\s+)?c$', before, re.I)
        or re.search(r'\bof\s*$', before, re.I)       # denominator: ``2 of 30``
        or (before.endswith('[') and after.startswith(']'))
    )


def _inactive_number(line, pos):
    # Wide enough for ``Previously this chart ranked 3``. This is intentionally used only
    # to exempt a number, never to prove the expected current assertion.
    start = max(0, pos - 64)
    boundary = max(line.rfind(x, start, pos) for x in '.!?;\n')
    prefix = line[max(start, boundary + 1):pos]
    negs = list(NEGATOR.finditer(prefix))
    if not negs:
        return False
    # Negation binds to the next numeric expression, not every later number in the window:
    # ``not 999 but 2`` negates 999 and asserts 2.
    return not NUMBER_RE.search(prefix[negs[-1].end():])


def _textval_rival_value(line, want, gold_lines):
    """Does this line assert a value for our quantity OTHER than the expected one?

    Three conditions, all referenced to gold's own sentence rather than to a position in
    ours, because the value's position moves between sites: it follows the anchor in
    "ranks **2** of 30", precedes it in "**1** times the leader", and is two numbers away
    in "**2** of the 30 charts have a leader".

    (a) A number gold uses appears MORE often than gold uses it: "ranks 30, not 2, of 30"
        doubles the 30, and no allowed-value set can see that because 30 is legitimate.

    (b) An active novel number appears in a sentence located as this claim.  It need not be
        joined to the expected value: ``ranks 999. It ranks 2`` is still contradictory.

    (c) A novel number explicitly marked as historical or negated is allowed. Direction
        matters: "not 999 but 2" is correct, while "999, not 2" asserts the rival.
    """
    flat = line.replace(',', '')
    matches = list(NUMBER_RE.finditer(flat))
    gold_flat = [s.replace(',', '') for s in gold_lines]
    gold_nums = [m.group(0) for s in gold_flat for m in NUMBER_RE.finditer(s)]

    # Compare ACTIVE uses, not raw multiplicity. The denominator in ``ranks 2 of 30`` is
    # context, while the first 30 in ``ranks 30, not 2, of 30`` is a competing value.
    for gv in set(gold_nums):
        got_active = sum(1 for m in matches if _num_eq(m.group(0), gv)
                         and not _context_number(flat, m.start(), m.end())
                         and not _inactive_number(flat, m.start()))
        gold_active = sum(1 for s in gold_flat for m in NUMBER_RE.finditer(s)
                          if _num_eq(m.group(0), gv)
                          and not _context_number(s, m.start(), m.end())
                          and not _inactive_number(s, m.start()))
        if got_active > gold_active:
            return True
    for m in matches:
        v, vs = m.group(0), m.start()
        if _num_eq(v, want) and _inactive_number(flat, vs):
            return True                               # expected value explicitly denied
        if any(_num_eq(v, gv) for gv in gold_nums):
            continue                                  # a value gold also uses
        if _context_number(flat, m.start(), m.end()):
            continue                                  # date, chart id, or citation
        # A superseded value may be mentioned historically: ``previously 3, now 2`` is a
        # correct repair, whereas ``3, not 2`` asserts the rival and denies ours.
        if _inactive_number(flat, vs):
            continue
        return True                                   # active competing value
    return False


def grade_textval(txt, anchors, expected, stale_txt=None, gold_txt=None):
    """Does the document state the expected value AND no longer state the stale one?

    Anchors locate the claim tolerantly; the comparison is exact. Presentation is
    tolerated, arithmetic is not.

    The second half matters as much as the first. Requiring only that the right value
    appear somewhere would let a file keep its stale sentence and append a correction - the
    workspace is still self-contradictory, and the benchmark's invariant is that every
    derived file AGREES with the source, not that it mentions the right number somewhere.

    Gold supplies the legitimate contextual figures in this claim (thresholds, chart
    counts, denominators). Candidate-only numbers must be explicit context or historical;
    otherwise they are competing assertions.
    """
    want = str(expected).replace(',', '')
    lines = _anchored(txt, anchors)
    if not lines:
        # Fail closed: a claim that cannot be located counts as not repaired. This grader
        # never defers to the LLM judge; where the paper scores a site with the judge, the
        # scorers call it separately (reconcilebench/judge_compare.py).
        return False
    if not any(_states(s, want) for s in lines):
        return False
    if stale_txt is not None and gold_txt is not None:
        # A COMPETING VALUE asserted for the same quantity. These cases pull in opposite
        # directions:
        #
        #   "the median is 999999999, not 75866"      must FAIL - a novel value asserted
        #   "ranks 30, not 2, of 30"                  must FAIL - and 30 is already in
        #                                              gold's sentence, so an allowed-value
        #                                              SET cannot see it
        #   "As of 2026, this chart ranks 2 of 30"    must PASS - 2026 is context
        #
        # Locating the value by POSITION relative to the anchor does not work: the value
        # follows the phrase in "ranks **2** of 30", precedes it in "**1** times the
        # leader", and is two numbers away in "**2** of the 30 charts have a leader".
        #
        # Gold's own sentence is the reliable reference. Two conditions, both derived from
        # it:
        #   (a) no number gold uses may appear MORE often than gold uses it -- that is what
        #       "30, not 2, of 30" does, and it needs no notion of position;
        #   (b) a number gold does not use may appear only as explicit context or as a
        #       negated/historical value. This is document-wide across every anchored
        #       sentence, so appending either the correction or the contradiction cannot
        #       change the answer.
        gold_lines = _anchored(gold_txt, anchors)
        if any(_textval_rival_value(s, want, gold_lines) for s in lines):
            return False
    return True


def _sg(site, code, cid, exp):
    """The shipped and gold text for this site, for the superseded-value check."""
    rel = rel_for(site, code, cid)
    return exp['shipped'].get(rel), _read(exp.get('gold_root') or '', rel)


def grade_site(site, root, code, cid, f, exp):
    if site == 'textval_atlas_record_note':
        # RETIRE: the note exists only because one entity held the atlas record. Removing it
        # is correct; so is rewriting it for the new holder. Leaving the old claim is not.
        rel = rel_for(site, code, cid)
        raw_p = os.path.join(root, rel)
        if not os.path.exists(raw_p):
            # Retiring the note is the intended action - but only as a deliberate removal,
            # not as a side effect of deleting the directory it lived in.
            return os.path.isdir(os.path.dirname(raw_p)) and len(
                os.listdir(os.path.dirname(raw_p))) > 5
        p = _safe_file(root, rel, MAX_TEXT_BYTES)
        if p is None:
            return False
        t = open(p, encoding='utf-8', errors='replace').read()
        # The last clause assumes the record MOVED. When the correction does not touch any
        # leader the record does not move, old and new are the same figure, and requiring the
        # old one to be absent would require the note to omit its own value.
        _moved = (exp['old_record_value'] != exp['new_record_value']
                  or exp['old_record_entity'] != exp['new_record_entity'])
        if not (exp['new_record_entity'].lower() in t.lower()
                and _fmt(exp['new_record_value']) in t
                and (not _moved or _fmt(exp['old_record_value']) not in t)):
            return False
        # No competing value, by the same shared rule as textval_atlas_overview.
        _g = _read(exp['gold_root'], rel_for(site, code, cid)) or ''
        _ref = [x for x in _g.split('\n') if x.strip()]
        return not any(_textval_rival_value(_l, _fmt(exp['new_record_value']), _ref)
                       for _l in t.split('\n') if _l.strip())

    txt = _read(root, rel_for(site, code, cid))
    if txt is None:
        return False

    # A document that asserts BOTH polarities of a claim has not repaired it, whichever
    # sentence came last. This is checked before either grading mode, because a stale
    # sentence left standing beside a correction is a contradiction under both.
    if site in ('textsem_flag_withdrawal', 'textsem_ratio_threshold'):
        body = re.sub(r'<!--.*?-->', ' ', txt, flags=re.S)
        if site == 'textsem_flag_withdrawal':
            # Only sentences about the review flag. Scanning the whole file would count the
            # textsem_ratio_threshold claim's correct wording ("the leader does not exceed
            # ...") as a withdrawal of the flag and fail a consistent document.
            flag_s = [x for x in _sentences(body) if re.search(r'review flag', x, re.I)]
            joined = ' '.join(flag_s)
            pos = re.findall(r'carries a \*{0,2}review flag|still carries', joined, re.I)
            neg = re.findall(r'no review flag|carries \*{0,2}no review|does not exceed',
                             joined, re.I)
        else:
            # anchored on the subject: "stands more than N times" is a substring of the
            # negative form "No entry stands more than N times", so an unanchored pattern
            # would match both polarities in gold itself.
            pos = re.findall(r'leading entry stands \*{0,2}more than [\d.]+ times',
                             body, re.I)
            neg = re.findall(r'no entry stands more than|every entry is at most', body, re.I)
        if pos and neg:
            return False                       # both asserted: self-contradictory

    if site == 'textsem_dominance':
        # The "dominates" claim: the rule behind it is written down nowhere. What a correct
        # repair looks like depends on whether the claim is still TRUE of whoever leads now:
        # if it is, restate it of them; if it is not, withdraw it. Requiring the positive
        # form unconditionally would demand an assertion that gold itself cannot justify,
        # and reject a correct withdrawal.
        body = re.sub(r'<!--.*?-->', ' ', txt, flags=re.S)
        old, new_ = exp['l3_entity'].lower(), f['leader'].lower()
        wins = [body.lower()[max(0, m.start() - 160):m.end() + 160]
                for m in re.finditer(r'dominat', body, re.I)]
        if not wins:
            return False                       # the claim was deleted, not restated
        if old != new_ and any(old in w for w in wins):
            return False                       # still asserted of the fallen entity
        neg = any(re.search(r'no entry|nothing|no longer|does not|do not|not\s+dominat|'
                            r'none of', w) for w in wins)
        if exp.get('l3_holds'):
            return any(new_ in w for w in wins) and not neg
        # The claim no longer holds: the repair must say so. Naming the new leader is
        # optional - "nothing dominates any longer" is a complete and correct repair.
        return neg
    if site == 'viz_vector':
        # RASTERISE, then measure what is actually drawn.
        #
        # An SVG is a program for painting pixels, and the only faithful question about it
        # is what it paints. A syntactic check would have to enumerate every way to hide or
        # fake a bar: display:none, a metadata-only leader, a full-canvas overlay, a
        # <circle> or <image>, width="100%" geometry, a 1x1 rect under
        # transform="scale(1000)", <defs> plus <use> referencing a cover.
        #
        # So the file is rendered and its bar proportions are read out of the raster with
        # the SAME decoder viz_raster uses on the PNG. Every case above fails for the reason
        # a human would give: the bars are not visible, or they are the wrong lengths. A
        # legitimate white background painted before the bars passes, because the bars are
        # still there afterwards.
        if not grade_viz_vector(txt, exp, cid):
            return False
        # The numeric leader label is still required, and is still a text claim: a correct
        # picture over a stale label is a contradiction in the same file.
        vis = re.sub(r'<(metadata|desc|title|defs)\b.*?</\1>', ' ', txt, flags=re.S | re.I)
        m = re.search(r'leader\s+([\d,.]+)', vis)
        return bool(m) and m.group(1).replace(',', '') == _fmt(f['maxv'])
    if site == 'exec_test':
        # EXECUTE the test, do not parse it.
        #
        # Parsing is easy to game: token presence accepts values in a comment; requiring an
        # equality accepts `assert x == v or True`; rejecting negation rejects the valid
        # `assert not (x != v)`. A test is a program, and the only faithful question about a
        # program is what it does when run.
        #
        # Metamorphic, so a vacuous test cannot pass: the suite must PASS against the
        # corrected data and FAIL against the stale data. `assert True` passes both and is
        # rejected for failing the second half.
        return grade_exec_test(root, cid, exp)

    if site == 'textsem_ratio_threshold':
        # The stated threshold must survive unaltered: rewriting "more than 5 times" as
        # "more than 2 times" would make the sentence true again without repairing
        # anything, and that is not a repair.
        want = _fmt(exp['thresh'][0])
        pos = bool(re.search(r'stands \*\*more than %s times\*\* the chart median'
                             % re.escape(want), txt, re.I))
        neg = bool(re.search(r'no entry stands more than %s times the chart median'
                             % re.escape(want), txt, re.I))
        return (pos or neg) and pos == exp['rel']['order_mag']
    if site == 'textsem_flag_withdrawal':
        # A consequence, not a number: when the threshold stops holding the sentence has to
        # be withdrawn, and renumbering it is not a repair.
        # Judge the sentence, not the wording: "Because the leader does not exceed 4 times
        # the chart median, this chart carries no review flag" is a correct paraphrase.
        # What must hold is that the stated threshold is untouched (rewriting it to fit the
        # new data is not a repair) and that the flag is withdrawn.
        wf = _fmt(exp['thresh'][1])
        # Split on sentence ends, not on every period, so a threshold of 2.5 is not cut
        # into "2" and "5".
        sent = [x for x in re.split(r'(?<=[.!?])\s+|\n', txt) if re.search(r'review flag', x, re.I)]
        if not sent:
            return False
        s0 = ' '.join(sent)
        # Match the number as a number: substring matching would accept a threshold
        # inflated tenfold, because "60" contains "6".
        nums = re.findall(r'\d+(?:\.\d+)?', s0)
        if wf not in nums:
            return False                      # threshold altered or dropped
        negated = bool(re.search(r'no review flag|not\s+carry|does not exceed|is within|'
                                 r'no longer|carries \*\*no', s0, re.I))
        pos, neg = (not negated), negated
        return (pos or neg) and pos == exp['rel']['flag']
    if site == 'textval_cross_rank':
        return grade_textval(txt, ['rank'], exp['rel']['rank'], *_sg(site, code, cid, exp))
    if site == 'textval_cross_ratio':
        return grade_textval(txt, ['times the leader'], exp['rel']['ratio'], *_sg(site, code, cid, exp))
    if site == 'textval_narr_leader':
        lead = [s for s in _sentences(txt) if 'leads with' in s.lower()]
        if not any(f['leader'].lower() in s.lower() for s in lead):
            return False
        old = exp['l3_entity'].lower()
        return not (old != f['leader'].lower()
                    and any(old in s.lower() for s in lead))
    if site in NARR_ANCHORS:
        return grade_textval(txt, NARR_ANCHORS[site], exp['narr'][site], *_sg(site, code, cid, exp))
    if site in SWEEP_ANCHORS:
        return grade_textval(txt, SWEEP_ANCHORS[site], exp['sweep'][site], *_sg(site, code, cid, exp))
    if site == 'textsem_superlative':
        # The superlative window must name the entity that leads NOW and must not still
        # name the former leader. Naming the new one alone is not enough: these are human
        # captions, and on a year-labelled series the new leader's token turns up for
        # unrelated reasons ("peaking in 2005, before decreasing from 2006"), so an
        # unrepaired caption could pass.
        body = re.sub(r'<!--.*?-->', ' ', txt, flags=re.S).lower()
        lead, old_lead = f['leader'].lower(), exp['l3_entity'].lower()
        wins = [body[max(0, m.start() - 140):m.end() + 140]
                for m in re.finditer(SUP_W, body, re.I)]
        # "must not still name the former leader" applies only when the lead changed hands.
        # Where it did not, the two names are the same string.
        return (any(lead in w for w in wins)
                and not (old_lead != lead and any(old_lead in w for w in wins)))
    if site == 'list_ranking':
        seen = re.findall(r'^\s*\d+\.\s*(.+?)\s*$', txt, re.M)
        vals = exp['values'][cid]
        if len(seen) != len(vals) or set(seen) != set(vals):
            return False
        return all(vals[seen[i]] >= vals[seen[i + 1]] for i in range(len(seen) - 1))
    if site in ('json_leader', 'json_mean', 'json_above_mean', 'json_share', 'json_verdict'):
        d = _json(txt)
        if not isinstance(d, dict):
            return False
        k = {'json_leader': 'leader', 'json_mean': 'mean', 'json_above_mean': 'above_mean',
             'json_share': 'share_pct', 'json_verdict': 'verdict'}[site]
        want = {'leader': f['leader'], 'mean': f['mean'], 'above_mean': f['above'],
                'share_pct': f['share'], 'verdict': f['verdict']}[k]
        got = d.get(k)
        if k in ('leader', 'verdict'):
            return str(got).strip().upper() == str(want).strip().upper()
        try:
            return (math.isfinite(float(got)) and math.isfinite(float(want))
                    and abs(float(got) - float(want)) < 1e-6)
        except (TypeError, ValueError):
            return False
    if site == 'textval_leader_margin':
        sv = f['values_sorted']
        return grade_textval(txt, ['runner-up'], round(100.0 * (sv[0] - sv[1]) / sv[1]),
                        *_sg(site, code, cid, exp))
    if site == 'textval_atlas_dashboard':
        rows = re.findall(r'\|\s*%s\s*\|([^|]*)\|([^|]*)\|([^|]*)\|' % re.escape(cid), txt)
        if not rows:
            return False
        # Every row for this chart must be right. Reading only the first would accept a table
        # that keeps its stale row and appends a corrected one.
        return all(a.strip() == f['leader'] and b.strip() == _fmt(f['mean'])
                   and c.strip().upper() == f['verdict'] for a, b, c in rows)
    if site == 'textval_atlas_overview':
        # The catalogue count must equal the number of charts in this instance.
        m = re.search(r'\*{0,2}([\d.]+)\*{0,2}\s+charts are catalogued', txt)
        if not m or not _num_eq(m.group(1), len(exp['values'])):
            return False
        # Presence is not exclusivity: "the highest value is 999999999, not 488151" states
        # the right figure and omits the stale one, yet asserts a rival. Uses the same
        # rival-value rule as the grade_textval sites, so context such as a date is allowed.
        _g = (_read(exp['gold_root'], rel_for(site, code, cid)) or '').split('\n')
        for _line in txt.split('\n'):
            if 'charts are catalogued' not in _line and 'highest single value' not in _line:
                continue
            _ref = [_gl for _gl in _g
                    if 'charts are catalogued' in _gl or 'highest single value' in _gl]
            # BOTH of this site's claims, not just the record. It asserts a chart count and
            # a maximum; guarding only the maximum would accept a rival asserted against the
            # count, as in "999999999, not 30 charts are catalogued".
            for _want in (_fmt(exp['global_max']), str(len(exp['values']))):
                if _textval_rival_value(_line, _want, _ref):
                    return False
        # Numeric, not textual: "482571.0" is the same figure as "482571".
        if not (any(_num_eq(x, _fmt(exp['global_max'])) for x in _nums(txt))
                and exp['global_leader'].lower() in txt.lower()
                and exp['global_chart'] in txt):
            return False
        # ... and the record it replaced must no longer be asserted here.
        old_v, old_e = _fmt(exp['old_record_value']), exp['old_record_entity']
        if old_v != _fmt(exp['global_max']) and old_v in txt:
            return False
        return not (old_e.lower() != exp['global_leader'].lower()
                    and old_e.lower() in txt.lower())
    if site == 'textval_atlas_leader_index':
        return grade_textval(txt, [('mean of chart leaders', 'average of chart leaders',
                               'average across chart leader', 'mean chart leader value')],
                        _fmt(exp['leader_mean']), *_sg(site, code, cid, exp))
    if site == 'textval_atlas_portfolio':
        return grade_textval(txt, ['charts have a leader'], exp['portfolio_n'],
                        *_sg(site, code, cid, exp))
    if site == 'control_revision_log':
        # Historical record. It is correct iff it still reports what was measured then:
        # the old entity at the old value, for the mutated chart, and not the new figure.
        line = next((l for l in txt.splitlines() if cid in l), None)
        if line is None:
            return False
        # What the log recorded for THIS chart. It defaults to the atlas record keys, which
        # coincide when the mutated chart holds the atlas record; log_entity/log_value cover
        # tasks that target another chart, such as the atlas floor. The "must not state the
        # new figure" clause is vacuous where the chart's leader did not move.
        ent = exp.get('log_entity') or exp['old_record_entity']
        val = exp.get('log_value', exp['old_record_value'])
        return (ent.lower() in line.lower()
                and _fmt(val) in line
                and (f['maxv'] == val or _fmt(f['maxv']) not in line))
    if site == 'viz_raster':
        return _read(root, 'figs/%s.png' % cid) == exp['gold_png']
    raise ValueError(site)


BAR_RGB = (76, 120, 168)          # #4c78a8, the bar colour the renderer uses


def decode_raster_bars(path, tol=12):
    """Recover the bar lengths a figure actually draws, normalised to the longest.

    Byte-hashing a PNG is not a validity test: it fails a correct rebuild drawn by a
    different matplotlib, and it passes a blank, truncated or copied file. Proportions are
    what the chart *claims*, they survive font and version differences, and nothing but a
    correct render reproduces them.
    """
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return None
    if not os.path.exists(path):
        return []
    try:
        im = np.array(Image.open(path).convert('RGB')).astype(int)
    except Exception:
        return []          # unreadable or truncated: no bars, therefore no claim
    hit = np.all(np.abs(im - np.array(BAR_RGB)) < tol, axis=-1)
    bars, prev = [], -9
    for y in range(hit.shape[0]):
        w = int(hit[y].sum())
        if w <= 3:
            continue
        if y - prev > 1:
            bars.append(w)
        else:
            bars[-1] = max(bars[-1], w)
        prev = y
    if not bars:
        return []
    top = float(max(bars))
    return [b / top for b in bars]


SVG_MAX_BYTES = 4 * 1024 * 1024
SVG_RENDER_TIMEOUT = 20
_RENDER_PROFILE = [None]


def _render_profile():
    """A sandbox profile that lets the renderer read its own interpreter and nothing else.

    The renderer loads local files an SVG references. resvg resolves no network reference,
    but local absolute paths are reachable, so an SVG containing no chart of its own, only
    `<image xlink:href="/abs/path/to/gold/figs/c25.svg"/>`, would render as gold and pass.

    Denying the repository and the home directory removes the reachable answer key, and the
    allow-backs are the interpreter and its site-packages, without which nothing renders.
    Stripping `href` attributes instead would be pattern matching against a surface that
    includes `xlink:href`, `use`, `feImage` and CSS `url()`; a capability boundary does not
    have to enumerate them. The same profile confines executed test suites (_run_suite).
    """
    if _RENDER_PROFILE[0]:
        return _RENDER_PROFILE[0]
    home = os.path.expanduser('~')
    allow = [os.path.dirname(os.path.dirname(sys.executable)),
             os.path.join(home, '.local/share/uv')]
    lines = ['(version 1)', '(allow default)',
             '(deny file-read* file-write* (subpath "%s") (subpath "%s"))'
             % (os.path.realpath(REPO), os.path.realpath(home))]
    for a in allow:
        if os.path.isdir(a):
            lines.append('(allow file-read* (subpath "%s"))' % os.path.realpath(a))
    d = tempfile.mkdtemp(prefix='rb_render_')
    lines.append('(allow file-read* file-write* (subpath "%s"))'
                 % os.path.realpath(tempfile.gettempdir()))
    path = os.path.join(d, 'render.sb')
    open(path, 'w').write('\n'.join(lines) + '\n')
    _RENDER_PROFILE[0] = path
    return path


def rasterise_svg(text):
    """Render SVG source to an RGB image, or None if it cannot be rendered.

    The input is written by the model under evaluation and is not trusted, so rendering
    happens in a subprocess, with a size cap, a timeout, and -- on a host with
    `sandbox-exec` -- no read access to this repository or the user's home. Without that
    last part the renderer would resolve `<image href="/abs/path/gold.svg">` and hand back
    gold's own bars. An oversized or unrenderable file yields None, which the caller treats
    as "draws nothing", never as "passes".
    """
    if not text or len(text.encode('utf-8', 'ignore')) > SVG_MAX_BYTES:
        return None
    src = ('import sys, resvg_py\n'
           'svg = sys.stdin.read()\n'
           'sys.stdout.buffer.write(bytes(resvg_py.svg_to_bytes(svg_string=svg)))\n')
    # -I so the interpreter does not put the current directory on sys.path, and cwd set to
    # a scratch directory: the grader normally runs from the repository root, which the
    # profile denies, and Python probing that path would raise PermissionError before the
    # renderer starts.
    cmd = [sys.executable, '-I', '-c', src]
    sb = shutil.which('sandbox-exec')
    if sb:
        cmd = [sb, '-f', _render_profile()] + cmd
    elif not os.environ.get('RB_ALLOW_UNSANDBOXED_RENDER'):
        raise RuntimeError(
            'grade_vis_atlas: sandbox-exec is unavailable, so the viz_vector site cannot render '
            'model-authored files without also letting them read gold. Grade in a '
            'container, or set RB_ALLOW_UNSANDBOXED_RENDER=1 for a run whose viz_vector verdicts '
            'will be discarded.')
    try:
        work = tempfile.mkdtemp(prefix='rb_svg_')
        try:
            r = subprocess.run(cmd, input=text.encode('utf-8'), cwd=work,
                               capture_output=True, timeout=SVG_RENDER_TIMEOUT)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    except Exception:
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    try:
        from PIL import Image
        import io
        return Image.open(io.BytesIO(r.stdout)).convert('RGB')
    except Exception:
        return None


def decode_vector_bars(im, tol=12):
    """decode_raster_bars, but from an already-open image. Same rule, one source of truth."""
    import numpy as np
    a = np.array(im).astype(int)
    hit = np.all(np.abs(a - np.array(BAR_RGB)) < tol, axis=-1)
    bars, prev = [], -9
    for y in range(hit.shape[0]):
        w = int(hit[y].sum())
        if w <= 3:
            continue
        if y - prev > 1:
            bars.append(w)
        else:
            bars[-1] = max(bars[-1], w)
        prev = y
    if not bars:
        return []
    top = float(max(bars))
    return [b / top for b in bars]


def grade_viz_vector(text, exp, cid, tol=0.06):
    """Do the bars this SVG actually paints agree with the source table?

    The chart's claim is: *these are the leading entries, in order, at these relative
    lengths*. So the drawn bars must be the sorted source values, longest first, as many
    as the shipped figure draws.

    Bars are compared in drawing order, never as a sorted multiset of lengths. A multiset
    would pass a chart whose rows are in the wrong order - in particular one that shortens
    the former leader's bar in place and leaves it at the top, so the picture still says
    the former entry leads.

    Lengths are relative because the figure carries no axis scale, so a uniform rescale of
    every bar is not a data error and is not treated as one - the same scope `viz_raster`
    declares for the PNG.
    """
    im = rasterise_svg(text)
    if im is None:
        return False                       # unrenderable: it draws nothing we can credit
    got = decode_vector_bars(im)
    vals = sorted(exp['values'][cid].values(), reverse=True)
    if not vals or vals[0] <= 0:
        return False
    # HOW MANY bars, not just which. Accepting any correct prefix would let a file draw two
    # bars of an eighteen-row chart and pass, or drop a row and keep credit. The row count
    # is not a free choice: the shipped figure states it, so a repair that changes it has
    # restructured the figure rather than corrected it. Measured from the SHIPPED file
    # rather than from gold, so the rule is "keep the figure you were given, with the right
    # data in it".
    shipped_svg = _read(exp.get('shipped_root') or '', 'figs/%s.svg' % cid)
    want_n = None
    if shipped_svg:
        sim = rasterise_svg(shipped_svg)
        if sim is not None:
            n = len(decode_vector_bars(sim))
            want_n = n if n >= 2 else None
    if want_n is None:                     # no reference count available: fall back
        want_n = min(len(vals), 10)
    if len(got) != want_n:
        return False
    if len(got) < 2:
        return False                       # no visible bars, or one degenerate one
    if len(got) > len(vals):
        return False                       # more bars than the table has rows
    want = [v / float(vals[0]) for v in vals[:len(got)]]
    # Drawing order, never sorted. Bars below the decoder's detection width vanish, and
    # they vanish from the TAIL because they are the smallest, so a truncated `got` still
    # aligns with the prefix of `want`.
    return all(abs(g - w) <= tol for g, w in zip(got, want))


def _csv_values(root, rel):
    try:
        p = _safe_file(root, rel, MAX_TEXT_BYTES)
        if p is None:
            return None
        rows = list(csv.reader(open(p, encoding='utf-8')))[1:]
        out = {}
        for r in rows:
            if len(r) < 2 or r[0] in out:
                return None
            value = float(r[1])
            if not math.isfinite(value):
                return None
            out[r[0]] = value
        return out
    except Exception:
        return None


def _csv_matches(root, rel, want):
    """Compare a source by its parsed values. Reformatting a CSV is not a data change, and
    scoring it as one is the same mistake as byte-hashing a figure."""
    got = _csv_values(root, rel)
    if got is None or set(got) != set(want):
        return False
    return all(abs(got[k] - float(want[k])) < 1e-6 for k in want)


def _run_suite(test_src, values, cid, gold_root, timeout=20):
    """Run the candidate test file against a given table. True iff it exits zero.

    Two things this has to get right.

    ISOLATION. This executes code written by the model under evaluation. The child gets a
    scrubbed environment, so it inherits no credentials such as an API key, and runs under
    the same sandbox profile as the SVG renderer, which denies the repository and the home
    directory (and with them every gold tree) and allows its own scratch workspace. A
    container isolates more strongly; this is what is enforceable on a host without one.

    FIDELITY. The suite runs against a full copy of the base workspace (`gold_root`; the
    caller passes the workspace under test) with ONLY the target table swapped, which is
    the difference the test is supposed to detect. A valid test that also reads charts.csv
    or anything under analysis/ therefore finds those files.
    """
    import tempfile, subprocess, shutil
    # copytree follows file symlinks by default. Reject them before the trusted grader
    # process copies an external target into the candidate's otherwise isolated scratch
    # workspace.
    for dp, ds, fs in os.walk(gold_root, followlinks=False):
        if any(os.path.islink(os.path.join(dp, x)) for x in ds + fs):
            return None
    tmp = tempfile.mkdtemp(prefix='testexec_')
    try:
        w = os.path.join(tmp, 'w')
        shutil.copytree(gold_root, w)
        with open(os.path.join(w, 'data', cid, 'values.csv'), 'w', newline='',
                  encoding='utf-8') as fh:
            wr = csv.writer(fh)
            wr.writerow(['label', 'value'])
            wr.writerows(values)
        os.makedirs(os.path.join(w, 'tests'), exist_ok=True)
        open(os.path.join(w, 'tests', 'test_atlas.py'), 'w',
             encoding='utf-8').write(test_src)
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
               'HOME': tmp, 'TMPDIR': tmp, 'PYTHONDONTWRITEBYTECODE': '1'}
        cmd = [sys.executable, '-I', 'tests/test_atlas.py']
        sb = shutil.which('sandbox-exec')
        if sb:
            cmd = [sb, '-f', _render_profile(), sys.executable, '-I',
                   'tests/test_atlas.py']
        elif not os.environ.get('RB_ALLOW_UNSANDBOXED_TESTS'):
            raise RuntimeError(
                'grade_vis_atlas: sandbox-exec is unavailable, so model-authored tests '
                'cannot be executed without giving them the filesystem. Grade in a '
                'container, or set RB_ALLOW_UNSANDBOXED_TESTS=1 for a run whose exec_test '
                'verdicts will be discarded.')
        r = subprocess.run(cmd, cwd=w, capture_output=True, timeout=timeout, env=env)
        return r.returncode == 0
    except Exception:
        return None                            # could not run it; refuse to judge
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def grade_exec_test(root, cid, exp):
    """Does this suite pass on the corrected data AND fail on the stale data?

    Only the target chart's `values.csv` is swapped between the two runs; everything else,
    including every derived file, stays exactly as the model shipped it. That choice fixes
    what the site means, so it is worth stating:

    - A test that compares a derived file against `values.csv` flips, and passes the site.
      That is the assertion the README says `tests/` carries.
    - A test that compares one derived file against another never flips, and fails the
      site. It cannot detect a change to the source of record, which is the only thing this
      benchmark ever changes.
    - A vacuous test (`assert x == v or True`, an uncollected function, a value in a
      comment) passes both runs and so fails the site. That is why the check executes the
      suite rather than parsing it.
    """
    src = _read(root, 'tests/test_atlas.py')
    if not src or not src.strip():
        return False
    post = list(exp['values'][cid].items())
    stale = _shipped_rows(exp, cid)
    if stale is None:
        return False
    # Base the run on the workspace UNDER test, not on gold, swapping only the target table.
    # A model may add assertions (for example about its own SVG) that its workspace meets and
    # gold does not. The question the site asks is whether the suite the model shipped
    # discriminates the corrected data from the stale data in the workspace the model shipped.
    base = root if os.path.isdir(root) else exp.get('gold_root')
    if not base or not os.path.isdir(base):
        return False
    ok_post = _run_suite(src, post, cid, base)
    ok_stale = _run_suite(src, stale, cid, base)
    if ok_post is None or ok_stale is None:
        return False
    return ok_post and not ok_stale


def _shipped_rows(exp, cid):
    """The chart's table as it shipped, parsed from the fixture."""
    txt = exp['shipped'].get('data/%s/values.csv' % cid)
    if not txt:
        return None
    out = []
    for r in list(csv.reader(txt.splitlines()))[1:]:
        if len(r) >= 2:
            try:
                out.append((r[0], float(r[1])))
            except ValueError:
                return None
    return out or None


def _bar_pixel_widths(path, tol=12):
    """Bar widths in pixels, not normalised. Used to ask whether a bar was near the
    decoder's detection threshold and so could legitimately vanish between renders."""
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return None
    if not os.path.exists(path):
        return None
    try:
        im = np.array(Image.open(path).convert('RGB')).astype(int)
    except Exception:
        return None
    hit = np.all(np.abs(im - np.array(BAR_RGB)) < tol, axis=-1)
    bars, prev = [], -9
    for y in range(hit.shape[0]):
        w = int(hit[y].sum())
        if w <= 3:
            continue
        if y - prev > 1:
            bars.append(w)
        else:
            bars[-1] = max(bars[-1], w)
        prev = y
    return bars


def grade_viz_raster(root, exp, cid, ref_root=None, tol=0.03):
    """Bar-proportion correctness, NOT full figure correctness.

    This decodes the drawn bar lengths and compares them against a reference render of the
    correct data through the same decoder. It says nothing about axis labels, titles or
    legends: erasing the entire label region leaves this passing. The site measures whether
    the figure ENCODES the right data, which is what the task changes; anything stated in
    the figure's text is out of its scope and the paper says so.

    Comparing to raw values requires every bar to be detectable, and on a chart whose
    largest value is hundreds of times its smallest the thin bars fall below a pixel and
    vanish. Decoding both sides the same way cancels the decoder's own blind spots, and a
    one-bar difference at the detection threshold is tolerated because antialiasing moves
    borderline bars between renders.
    """
    rel = 'figs/%s.png' % cid
    got_path = _safe_file(root, rel, MAX_BINARY_BYTES)
    if got_path is None:
        return False
    got = decode_raster_bars(got_path)
    if got is None:
        # Pillow missing. A byte comparison is NOT an equivalent fallback: it fails every
        # correct re-render made in a different environment, which is the defect this
        # function exists to avoid. Refuse to grade rather than degrade silently.
        raise RuntimeError(
            'grade_vis_atlas: pillow is not installed. viz_raster cannot be graded by decoding '
            'and the byte fallback penalises every correct re-render made in a different '
            'environment - it silently invalidated every viz_raster verdict in this project. '
            'Install pillow before grading.')
    ref_root = ref_root or exp.get('ref_root')
    ref_path = _safe_file(ref_root, rel, MAX_BINARY_BYTES) if ref_root else None
    want = decode_raster_bars(ref_path) if ref_path else None
    if want is None:                       # no reference available: fall back to values
        vals = sorted(exp['values'][cid].values(), reverse=True)
        top = float(max(vals))
        want = [v / top for v in vals]
    # How much of a count difference is renderer noise, and how much is a dropped row?
    #
    # A flat +-1 would admit a genuinely missing bar. But requiring equality would be wrong
    # here in a way it is not for the SVG, because this count is not a property of the file
    # -- it is the decoder's 3-pixel threshold interacting with the data, and the data is
    # what changed. Gold and shipped renders of one chart can differ by several bars for
    # exactly that reason.
    #
    # So the tolerance is spent only where the threshold can explain it: the candidate may
    # be SHORT by one bar when the reference's own last bar is within a pixel or two of the
    # detection width, i.e. it was about to vanish anyway. Anything else must match. A bar
    # dropped from the MIDDLE already fails the elementwise comparison below, because every
    # later bar shifts.
    if len(got) > len(want):
        return False
    if len(got) < len(want):
        if len(want) - len(got) > 1:
            return False
        ref_px = _bar_pixel_widths(os.path.join(ref_root, 'figs/%s.png' % cid)) \
            if ref_root else None
        if not ref_px or ref_px[-1] > 6:
            return False               # the missing bar was comfortably visible
    n = min(len(got), len(want))
    # Compare in drawing order. Sorting both sides first would accept a figure whose bar
    # lengths were reassigned to the wrong row labels - the picture is wrong while the
    # multiset of lengths is right.
    a, b = got[:n], want[:n]
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def claim_line_index(site, exp):
    """Which line of its file carries THIS site's claim, asked of the grader itself.

    Several sites share a file: the narrative holds five, the relations file four, the
    profile three. "The first line that differs between shipped and gold" would therefore
    name the FIRST site's claim for every one of them.

    Rather than re-deriving each site's anchors here, and risking a second locator that
    disagrees with the real one, revert one differing line at a time to its stale text and
    ask whether that site's verdict flips. The line that flips it is, by construction, the
    line the grader reads. Returns None when no single line decides the site.
    """
    import tempfile as _tf, shutil as _sh
    rel = rel_for(site, exp['code'], exp['target'])
    if not rel or not rel.endswith(('.md', '.txt')):
        return rel, None
    gold = _read(exp['gold_root'], rel)
    ship = (exp.get('shipped') or {}).get(rel) or _read(exp['shipped_root'], rel)
    if gold is None or ship is None:
        return rel, None
    gl, sl = gold.split('\n'), ship.split('\n')
    idx = [k for k, (a, b) in enumerate(zip(gl, sl)) if a != b and a.strip()]
    if len(idx) <= 1:
        return rel, (idx[0] if idx else None)
    for k in idx:
        tmp = _tf.mkdtemp(prefix='claimline_')
        try:
            w = os.path.join(tmp, 'w')
            _sh.copytree(exp['gold_root'], w)
            L = gl[:]
            L[k] = sl[k]
            open(os.path.join(w, rel), 'w', encoding='utf-8').write('\n'.join(L))
            if grade(w, exp, only={site})['outcomes'].get(site) != 'ok':
                return rel, k
        finally:
            _sh.rmtree(tmp, ignore_errors=True)
    return rel, None


def _resolve(exp):
    """Point the fixture at the checkout it is actually in.

    task.json records absolute roots from the machine that built the corpus. Rewriting the
    tracked files at runtime would dirty every clone, and reading the roots as-is would
    grade somebody else's tree. Derive them instead, from the task id, and treat the stored
    value as advisory.
    """
    tid = exp.get('task_id')
    if not tid:
        return exp
    # Health and RNA-label fixtures name their task folder; VisText-General is the default.
    d = os.path.join(REPO, 'tasks', exp.get('suite') or 'general', tid)
    if not os.path.isdir(d):
        return exp
    want = {'shipped_root': os.path.join(d, 'workspace'),
            'gold_root': os.path.join(d, 'gold')}
    if all(exp.get(k) == v for k, v in want.items()):
        return exp
    e = dict(exp)
    e.update(want)
    return e


def _presence(site):
    """How this claim may legitimately disappear. Read from claim_rules, which is where the
    policy is written; imported lazily because claim_rules imports this module."""
    try:
        import claim_rules as _CR
        return _CR.PRESENCE.get(site, 'required')
    except Exception:
        return 'required'


def grade(root, exp, only=None):
    """Grade a workspace. `only` restricts the work to a set of sites.

    The restriction is an optimisation, not a semantic: each site is decided independently,
    so grading one gives the same verdict as grading all of them. It matters because
    `viz_vector` rasterises and `exec_test` executes in a sandbox, so every site graded
    spawns subprocesses a single-site caller has no use for.
    """
    # Resolve the REFERENCE roots inside exp, and then the root the caller handed us. Call
    # sites pass exp['shipped_root'] or exp['gold_root'] straight through, so that root must
    # be remapped too, or it would still point at the machine that built the corpus.
    stored_ship, stored_gold = exp.get('shipped_root'), exp.get('gold_root')
    exp = _resolve(exp)
    if root and root == stored_ship:
        root = exp['shipped_root']
    elif root and root == stored_gold:
        root = exp['gold_root']
    cid, code, f = exp['target'], exp['code'], exp['f_post']
    broken, out, states = set(exp['broken']), {}, {}

    for site in exp['sites']:
        if only is not None and site not in only:
            continue
        rel = rel_for(site, code, cid)
        cur, shipped = _read(root, rel), exp['shipped'].get(rel)
        if site == 'viz_raster':
            if cur is None:
                out[site], states[site] = 'destroyed', 'damaged'
            elif cur == exp['gold_png']:
                out[site], states[site] = 'ok', 'repaired'
            elif grade_viz_raster(root, exp, cid, ref_root=exp['gold_root']):
                out[site], states[site] = 'ok', 'repaired'
            elif cur == exp['shipped_png']:
                out[site], states[site] = 'miss', 'stale'
            else:
                out[site], states[site] = 'wrong', 'damaged'
            continue
        ok = grade_site(site, root, code, cid, f, exp)
        if cur is None or not (cur or '').strip():
            # An absent file is damage -- EXCEPT where the claim's presence policy
            # (claim_rules.PRESENCE) says the artifact may be retired, and the site's own check
            # accepted this particular removal as a deliberate one. textval_atlas_record_note
            # is such a claim: the note asks to be retired when the record passes to another
            # entry, so removing it is a correct repair, consistent with the judge's prompt.
            if ok and _presence(site) == 'retirable':
                out[site], states[site] = 'ok', 'retired'
            else:
                out[site], states[site] = 'destroyed', 'damaged'
        elif ok:
            out[site] = 'ok'
            states[site] = ('repaired' if site in broken
                            else 'intact' if cur == shipped else 'rewritten-ok')
        else:
            out[site] = 'wrong' if cur != shipped else 'miss'
            states[site] = 'stale' if site in broken else 'damaged'

    touched, damaged, total = [], [], 0
    for other in exp['others']:
        oc, of = exp['codes'][other], exp['other_facts'][other]
        # Every derived artifact an untouched chart owns, so destroying any of them is
        # reported as damage and cannot coexist with exact_match.
        for site, rel in (('textsem_superlative', 'analysis/%s-review.md' % oc),
                          ('list_ranking', 'analysis/%s-ranking.md' % oc),
                          ('json_leader', 'analysis/%s-stats.json' % oc),
                          ('textval_leader_margin', 'analysis/%s-segment.md' % oc),
                          (None, 'analysis/%s-profile.md' % oc),
                          (None, 'analysis/%s-narrative.md' % oc),
                          (None, 'analysis/%s-relations.md' % oc),
                          (None, 'analysis/%s-editorial.md' % oc),
                          (None, 'figs/%s.png' % other),
                          (None, 'data/%s/values.csv' % other)):
            total += 1
            if _read(root, rel) == exp['shipped'].get(rel):
                continue
            touched.append(rel)
            if site:
                still = grade_site(site, root, oc, other, of, exp)
            elif rel.endswith('.png'):
                # The render script redraws every figure, so an untouched chart's PNG moves
                # whenever the build step runs. Reference is the SHIPPED figure: that chart's
                # data never changed, so a faithful redraw must decode the same way.
                still = grade_viz_raster(root, exp, other, ref_root=exp['shipped_root'])
            elif rel.endswith('.csv'):
                # a source on an untouched chart: reformatting is fine, changed data is not
                still = _csv_matches(root, rel, exp['values'][other])
            else:
                # An untouched chart's prose: any edit that empties it is damage. A
                # rewrite that preserves its numbers is not, so compare the figures it
                # states rather than its bytes.
                cur_t = _read(root, rel) or ''
                old_t = exp['shipped'].get(rel) or ''
                still = bool(cur_t.strip()) and (
                    set(re.findall(r'\d+(?:\.\d+)?', cur_t)) ==
                    set(re.findall(r'\d+(?:\.\d+)?', old_t)))
            if not still:
                damaged.append(rel)

    # The target chart's OWN files. The loop above protects every chart the change did not
    # touch, and deliberately skips the target's files because the model is supposed to edit
    # them. Being free to edit the claims does not license deleting unrelated content: a
    # correct repair is minimal, the principle the preservation sites and the revision log
    # also encode.
    #
    # The test is narrow on purpose. Prose that states no figure cannot be part of the
    # repair, so its removal is damage; any sentence carrying a claim stays entirely free to
    # be rewritten, which is what the model was asked to do.
    for rel in _target_prose(exp):
        old_t, cur_t = exp['shipped'].get(rel), _read(root, rel)
        if old_t is None or cur_t == old_t:
            continue
        if cur_t is None or not cur_t.strip():
            damaged.append(rel)
            continue
        if _inert_lost(old_t, cur_t):
            damaged.append(rel)

    hit = [s for s in exp['broken'] if out.get(s) == 'ok']
    nulls = [s for s in exp['sites'] if s not in broken]

    # within-file completion: for every file holding more than one broken claim, did the
    # model fix all of them or stop early? All-or-nothing files cannot show satisficing;
    # only independently-editable claims in one file can.
    per_file = {}
    for s in exp['broken']:
        per_file.setdefault(rel_for(s, code, cid), []).append(out.get(s) == 'ok')
    multi = {k: v for k, v in per_file.items() if len(v) > 1}
    wf = dict(files=len(multi),
              all_fixed=sum(1 for v in multi.values() if all(v)),
              partial=sum(1 for v in multi.values() if any(v) and not all(v)),
              none=sum(1 for v in multi.values() if not any(v)),
              detail={k.split('/')[-1]: '%d/%d' % (sum(v), len(v)) for k, v in multi.items()})
    return dict(
        probe='ATLAS', target=cid, code=code,
        rr='%d/%d' % (len(hit), len(exp['broken'])), repaired=hit,
        stale=[s for s in exp['broken'] if out.get(s) != 'ok'],
        outcomes=out, states=states,
        by_depth=_grp(exp['broken'], out, DEPTH),
        by_pattern=_grp(exp['broken'], out, PATTERN),
        by_reach=_grp(exp['broken'], out, REACH),
        null_sites={s: states.get(s) for s in nulls}, within_file=wf,
        bulk_files=total, bulk_touched=touched, bulk_damaged=damaged,
        # falsified, not merely touched: an edit that leaves the record correct is fine
        history_intact=(out.get('control_revision_log') == 'ok'),
        history_untouched=(states.get('control_revision_log') == 'intact'),
        control_touched=(_read(root, 'notes/methodology.md')
                         != exp['shipped'].get('notes/methodology.md')),
        control_intact=_control_ok(root, exp),
        source_edit_ok=_csv_matches(root, 'data/%s/values.csv' % cid, exp['values'][cid]),
        build_step_run=(_read(root, 'figs/%s.png' % cid) != exp['shipped_png']),
        exact_match=(all(out.get(s) == 'ok' for s in exp['sites']) and not damaged
                     and _tree_matches_gold(root, exp)),
    )


def _target_prose(exp):
    """Markdown the target chart owns -- the files a repair is expected to rewrite."""
    c = exp['code']
    return ['analysis/%s-%s.md' % (c, k)
            for k in ('profile', 'narrative', 'relations', 'editorial', 'review', 'segment')]


def _inert_lost(old_t, cur_t):
    """Did one of the generator's filler paragraphs disappear?

    Tested against the generator's own FILLER text rather than a heuristic. Treating
    "contains no digit" as "states no claim" would flag gold itself: the dominance claim
    carries no digits, so gold rewriting it would look like deletion. The filler is a fixed,
    known set of paragraphs that depend on nothing, which is exactly the content a
    correction gives no reason to touch -- so it can be named instead of inferred.

    Matching is fuzzy and generous. The point is to catch a paragraph being dropped, not to
    police prose: a model that reworded the filler has still preserved it.
    """
    import difflib
    cur = [p.strip() for p in re.split(r'\n\s*\n', cur_t) if p.strip()]
    for p in _FILLER():
        if p not in old_t:
            continue                              # this file never carried it
        if not any(difflib.SequenceMatcher(None, p, q).ratio() >= 0.5 for q in cur):
            return True
    return False


def _FILLER():
    """The generator's inert paragraphs, read from the generator so they cannot drift."""
    global _FILLER_CACHE
    try:
        return _FILLER_CACHE
    except NameError:
        pass
    try:
        import gen_vis_atlas
        _FILLER_CACHE = tuple(gen_vis_atlas.FILLER)
    except Exception:
        _FILLER_CACHE = ()
    return _FILLER_CACHE


def _tree_matches_gold(root, exp):
    """Is this workspace the same as gold, file for file?

    Comparing only the SET of numeric tokens per file would pass a blanked README, an added
    file, a corrupted label and a garbled foreign profile. This compares the path sets and
    then each file by a comparator suited to its type: sources are parsed as CSV, figures are decoded, prose is compared on its normalised
    text rather than its bytes so that reflowing is allowed and rewording is not.
    """
    gold = exp.get('gold_root')
    if not gold or not os.path.isdir(gold):
        return None                            # cannot tell; do not claim success

    def paths(rt):
        out = set()
        for dp, _, fs in os.walk(rt):
            for fn in fs:
                if fn.endswith(('.pyc',)) or '__pycache__' in dp:
                    continue
                out.add(os.path.relpath(os.path.join(dp, fn), rt))
        return out

    have, want = paths(root), paths(gold)
    if have != want:
        return False                           # missing or unexpected files

    for rel in sorted(want):
        if rel.endswith('.png'):
            cid = os.path.splitext(os.path.basename(rel))[0]
            ap = _safe_file(root, rel, MAX_BINARY_BYTES)
            bp = _safe_file(gold, rel, MAX_BINARY_BYTES)
            if ap is None or bp is None:
                return False
            a = decode_raster_bars(ap)
            b = decode_raster_bars(bp)
            if a is None or b is None:
                return None                    # decoder unavailable: refuse to judge
            if len(a) != len(b) or any(abs(x - y) > 0.03 for x, y in zip(a, b)):
                return False
            continue
        a, b = _read(root, rel), _read(gold, rel)
        if a is None or b is None:
            return False
        if rel.endswith('.csv'):
            if [r for r in csv.reader(a.splitlines())] != \
               [r for r in csv.reader(b.splitlines())]:
                return False
            continue
        if ' '.join(a.split()) != ' '.join(b.split()):
            return False
    return True


def _control_ok(root, exp):
    """The control describes collection procedure and states no figure. It is violated when
    it starts making a value claim - not when someone fixes its whitespace."""
    t = _read(root, 'notes/methodology.md')
    if not t or not t.strip():
        return False
    return (_fmt(exp['old_record_value']) not in t
            and _fmt(exp['f_post']['maxv']) not in t)


def _grp(broken, out, table):
    d = {}
    for s in broken:
        k = str(table[s])
        a, b = d.get(k, (0, 0))
        d[k] = (a + (1 if out.get(s) == 'ok' else 0), b + 1)
    return {k: '%d/%d' % v for k, v in sorted(d.items())}
