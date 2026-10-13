"""The atlas construction of gen_vis_atlas.py, with the target series chosen in advance.

`gen_vis_atlas.build_instance` corrects whichever chart holds the global maximum of the window it
is given, so the subject of a workspace is decided by magnitude, and a series that is not the
largest in its window can never be the target. The VisText-Health workspaces need a chosen health
series as the target, so this module builds the window around it: the chosen chart holds the
global maximum by construction, and everything after that (the correction, the caption check, the
contract) is gen_vis_atlas's, reused rather than reimplemented.

    build_for(u, pool, n_charts, mode, variant, seed)   the workspace whose target is `u`
    retarget_thresholds(inst)                            thresholds the correction crosses

gen_bixbench.py uses the same threshold selection for the RNA condition-label workspaces.
"""
import os, re, sys, random

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_vis_atlas as A
from gen_vis import _caption_ok


def _maxv(u):
    return max(v for _, v in u['rows'])


# A harvested caption can assert the leader's margin as well as its identity: "Fashion &
# Clothing has almost double every other category". Renaming the leader carries the name across
# and leaves the margin behind, so the reference would assert something false: the new leader is
# mid-pack by construction. gen_vis_atlas removes margins written as numbers; this catches the
# same claim written in words.
_MARGIN_CLAIM = (r'\b(?:almost|nearly|about|roughly|over|more than|under|less than)?\s*'
                 r'(?:double|triple|twice|three times|four times|half)\b'
                 r'|\bcombined\b|\bas much as\b|\bas many as\b|\ball other\b'
                 r'|\bevery other\b')


def admissible(u, min_rows=12, max_rows=60):
    """The filter `build_instance` applies to every chart it picks, applied here so the
    window can be assembled from charts that will actually survive it."""
    if not min_rows <= len(u['rows']) <= max_rows:
        return False
    if re.search(_MARGIN_CLAIM, u.get('caption') or '', re.I):
        return False
    f = A.chart_facts(u['rows'])
    if not _caption_ok(u, f):
        return False
    sv = sorted((v for _, v in u['rows']), reverse=True)
    return len(sv) >= 4 and sv[0] > sv[1] > 0


def window_for(u, pool, n_charts, seed=0, min_rows=12, max_rows=60):
    """A pool ordered so that exactly `n_charts` are picked and `u` is the target.

    Three properties matter, and all three are structural:

      * every other chart's maximum is below `u`'s, so `u` holds the global maximum and the
        atlas-wide aggregates depend on it;
      * at least one other chart's maximum is above `u`'s runner-up, so that after the
        correction `u` loses its place at the top (`build_instance` rejects the workspace
        otherwise, and the cross-rank claim would not move);
      * `u` sits at a seeded position inside the window rather than at its head. Chart ids are
        assigned in pick order, so heading the window would make the target `c01` in every
        workspace, a cue an agent could learn instead of finding the change.

    The second is checked by the caller rather than left to fail deep inside
    `build_instance`, which returns None with no reason attached.
    """
    top = _maxv(u)
    others = [x for x in pool
              if x['img_id'] != u['img_id'] and _maxv(x) < top
              and admissible(x, min_rows, max_rows)]
    rng = random.Random(seed)
    rng.shuffle(others)
    head = others[:n_charts - 1]
    at = rng.randrange(n_charts) if len(head) == n_charts - 1 else 0
    return head[:at] + [u] + head[at:] + others[n_charts - 1:], len(others)


def build_for(u, pool, n_charts, mode='overwrite', variant=0, seed=0):
    """Build a workspace whose target is `u`. Returns (inst, reason)."""
    if not admissible(u):
        return None, 'target fails the chart filter (rows, caption gate, or tied leader)'
    sv = sorted((v for _, v in u['rows']), reverse=True)
    win, n_below = window_for(u, pool, n_charts, seed)
    if n_below < n_charts - 1:
        return None, 'only %d charts rank below this one; need %d' % (n_below, n_charts - 1)
    if not any(_maxv(x) > sv[1] for x in win[:n_charts] if x['img_id'] != u['img_id']):
        return None, ('no chart in the window outranks the target runner-up (%s), so the '
                      'target would keep the top spot after deflation' % A._fmt(sv[1]))
    inst = A.build_instance(win, n_charts, mode, variant)
    if inst is None:
        return None, 'build_instance rejected it (threshold, caption rename, or median gate)'
    if inst['pre'][inst['target']]['u']['img_id'] != u['img_id']:
        return None, 'window assembly failed: target is a different chart'
    if not retarget_thresholds(inst):
        return None, 'no threshold the correction crosses under the median convention in use'
    if _count_collision(inst):
        return None, ('the superseded atlas maximum renders as the chart count, which the '
                      'overview sentence cannot distinguish')
    return inst, 'ok'


def _count_collision(inst):
    """Does the superseded atlas maximum render exactly as the chart count?

    `analysis/overview.md` states two numbers in one sentence: how many charts are catalogued,
    and the highest single value anywhere. The grader requires the new figure to be present and
    the superseded one to be absent, and cannot tell one number from another, so when the old
    maximum renders as the chart count (forty charts, old maximum 40) the reference would fail
    its own site. Such a workspace is rejected at construction: a reader could not tell the two
    numbers apart either.
    """
    n = A._fmt(len(inst['order']))
    old = max(inst['pre'][c]['f']['maxv'] for c in inst['pre'])
    return A._fmt(old) == n


THRESH_OPTS = (1.5, 2, 2.5, 3, 4, 5, 6, 8, 10)


def retarget_thresholds(inst):
    """Choose the two thresholds against the median the workspace actually states.

    `build_instance` picks them from `sorted(values)[n//2]`, an ascending sort, while every
    document that states a median uses `sorted(values, reverse=True)[n//2]`, as does
    `claim_rules.chart`. For an odd number of entries the two agree; for an even number they
    differ, and a threshold chosen against the ascending median can fail to be crossed by the
    correction, leaving the two threshold claims unchanged. This picks thresholds the
    correction crosses under the stated median. The VisText-General workspaces
    (tasks/general) do not use this and keep `build_instance`'s choice.
    """
    cid = inst['target']
    pre, post = inst['pre'][cid]['f'], inst['post'][cid]['f']
    pre_r = pre['maxv'] / pre['values_sorted'][len(pre['values_sorted']) // 2]
    post_r = post['maxv'] / post['values_sorted'][len(post['values_sorted']) // 2]
    opts = [t for t in THRESH_OPTS if post_r < t <= pre_r]
    if not opts:
        return False
    A._THRESH[0] = float(opts[len(opts) // 2])
    A._THRESH[1] = float(opts[0] if len(opts) == 1 else opts[max(0, len(opts) // 2 - 1)])
    return True
