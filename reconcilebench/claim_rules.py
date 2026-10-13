"""How each claim is derived from the sources -- stated, not implied.

The benchmark's subject is documents whose derivation rules are not obvious, and a grader that
does not know the rule cannot tell a correct repair from a wrong one either. A judge shown only
the data has to *guess* the convention, and where it guesses differently from the generator it
marks a correct model wrong -- on the median alone the ordinary `statistics.median` disagrees
with this corpus on 52% of instances, because the generator takes an element rather than
averaging the two middle ones.

So each rule is written down here in three forms: prose for the judge, the generator's own
expression for the record, and an executable form. The executable form keeps the other two
honest -- `verify()` runs every rule against every instance and checks it reproduces the
figure gold actually states, so a rule that drifts from the generator fails loudly instead of
quietly mis-grading.
"""
import os, re, sys, json, glob

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def chart(vals):
    """The per-chart facts the generator derives, recomputed from a label->value list."""
    sv = sorted((v for _, v in vals), reverse=True)
    n = len(vals)
    mean = round(sum(v for _, v in vals) / n, 1)
    above = sum(1 for _, v in vals if v > mean)
    share = int(round(100.0 * above / n))
    return dict(sv=sv, n=n, mean=mean, above=above, share=share,
                verdict='MAJORITY' if share > 50 else 'MINORITY',
                leader=max(vals, key=lambda p: p[1])[0],
                maxv=max(v for _, v in vals),
                med=sv[len(sv) // 2])


# Each rule: what quantity it is, the convention in words, the generator's expression, and a
# callable over (F, ATLAS, CID, THRESH) -> value.  F is this chart's facts; ATLAS maps chart
# id -> facts for every chart in the instance.

# How the claim may legitimately disappear. This is a property of the claim, not a global
# policy, so it is recorded per claim and shown to the judge as "Presence":
#
#   required      the sentence must still be there, stating the new value
#   withdrawable  the claim may lapse; it must then be negated or simply not asserted, but
#                 the sentence has to remain and say something true
#   retirable     the artifact exists only because the claim held; removing it is a valid
#                 repair once it does not
PRESENCE = {
    'textval_chart_median':          'required',
    'textval_chart_tail':            'required',
    'textval_narr_leader':           'required',
    'textval_narr_value':            'required',
    'textval_narr_above':            'required',
    'textval_narr_gap':              'required',
    'textsem_ratio_threshold':       'withdrawable',
    'textsem_flag_withdrawal':       'withdrawable',
    'textval_cross_rank':            'required',
    'textval_atlas_mean':            'required',
    'textval_atlas_third':           'required',
    'textval_atlas_spread':          'required',
    'textval_atlas_concentration':   'required',
    'textval_leader_margin':         'required',
    'textsem_superlative':           'required',
    'textval_cross_ratio':           'required',
    'textval_atlas_leader_index':    'required',
    'textval_atlas_portfolio':       'required',
    'textval_atlas_overview':        'required',
    'textval_atlas_record_note':     'retirable',
    'textval_atlas_dashboard':       'required',
    'textsem_dominance':             'withdrawable',
}

RULES = {
 'textval_chart_median': dict(
   presence='required',
   defn='An in-chart sweep: the chart’s median entry.',
   quantity="the chart's median entry",
   prose="Sort this chart's values from largest to smallest and take the element at index "
         "len//2 (0-based). For an even number of entries this is an actual entry, the "
         "lower of the two middle values -- NOT the average of them.",
   expr="sv = sorted(values, reverse=True); sv[len(sv)//2]",
   fn=lambda F, A, C, T: F['med']),

 'textval_chart_top3': dict(
   fixed='The comparison is over the THREE largest entries. Widening or narrowing that to four, five or "the top entries" so an old percentage reads true again is a WRONG repair.',
   defn='An in-chart sweep: the top three entries’ share.',
   quantity="the share of this chart's total held by its three largest entries",
   prose="Sum the three largest values, divide by the sum of all values, multiply by 100 "
         "and round to a whole number of percent.",
   expr="round(100.0 * sum(sv[:3]) / sum(sv))",
   fn=lambda F, A, C, T: round(100.0 * sum(F['sv'][:3]) / sum(F['sv']))),

 'textval_chart_tail': dict(
   presence='required',
   fixed='The cut-off is HALF the leader. That fraction is part of the claim: restating it against a third, a quarter or any other fraction so an old count reads true again is a WRONG repair.',
   defn='An in-chart sweep: how many entries fall below half the leader.',
   quantity="how many entries fall below half the leader's value",
   prose="Count the values strictly less than half the largest value. Strictly less than: "
         "a value exactly equal to half the leader is NOT counted.",
   expr="sum(1 for v in sv if v < sv[0] / 2.0)",
   fn=lambda F, A, C, T: sum(1 for v in F['sv'] if v < F['sv'][0] / 2.0)),

 'textval_narr_leader': dict(
   presence='required',
   defn='Commentary naming the leader. Scattered prose: five independent claims sit in one file with inert paragraphs between them, so a model that fixes the first and moves on scores one of five.',
   quantity="which entry leads the chart",
   prose="The label of the row with the largest value.",
   expr="max(rows, key=value)[label]",
   fn=lambda F, A, C, T: F['leader']),

 'textval_narr_value': dict(
   presence='required',
   defn='Commentary stating the leader’s value.',
   quantity="the leader's value",
   prose="The largest value in the chart, written as the source writes it.",
   expr="sv[0]",
   fn=lambda F, A, C, T: F['sv'][0]),

 'textval_narr_top3': dict(
   fixed='The comparison is over the THREE largest entries. Widening or narrowing it so an old percentage reads true again is a WRONG repair.',
   defn='Commentary stating the top three entries’ share of the total.',
   quantity="the share of the total held by the three largest entries",
   prose="Sum the three largest values, divide by the sum of all values, multiply by 100 "
         "and round to a whole number of percent.",
   expr="round(100.0 * sum(sv[:3]) / sum(sv))",
   fn=lambda F, A, C, T: round(100.0 * sum(F['sv'][:3]) / sum(F['sv']))),

 'textval_narr_above': dict(
   presence='required',
   fixed='The reference point is the MEAN. Switching it to the median, or to any other centre, so an old count reads true again is a WRONG repair.',
   defn='Commentary stating how many entries sit above the mean.',
   quantity="how many entries sit above the mean",
   prose="Take the mean of all values ROUNDED TO ONE DECIMAL PLACE, then count the values "
         "strictly greater than that rounded mean. Rounding before comparing can change "
         "the count, so round first.",
   expr="mean = round(sum(vals)/n, 1); sum(1 for v in vals if v > mean)",
   fn=lambda F, A, C, T: F['above']),

 'textval_narr_gap': dict(
   presence='required',
   defn='Commentary stating the gap between first and last entry.',
   quantity="the gap between the first and last entry",
   prose="Largest value minus smallest value, rounded to one decimal place.",
   expr="round(sv[0] - sv[-1], 1)",
   fn=lambda F, A, C, T: round(F['sv'][0] - F['sv'][-1], 1)),

 'textsem_ratio_threshold': dict(
   presence='withdrawable',
   fixed='The multiple is fixed for this instance and is given in CORRECT VALUE below. Lowering it so the old sentence reads true again is a WRONG repair, even though the rewritten sentence may be arithmetically true.',
   defn='Whether the leading entry exceeds a stated multiple of the chart median. After the change the comparison may simply be FALSE, and the repair is to negate it — there is no substitute value.',
   quantity="whether the leading entry exceeds a stated multiple of the chart median",
   prose="Compare the largest value against the instance's multiple times the chart "
         "median (median by the rule above: descending sort, element at len//2). The "
         "claim holds only if leader >= multiple * median. If it does not hold there "
         "is no replacement figure: the sentence must be negated.",
   expr="sv[0] >= t_ord * med",
   fn=lambda F, A, C, T: F['sv'][0] >= T[0] * F['med']),

 'textsem_flag_withdrawal': dict(
   presence='withdrawable',
   fixed='The flag multiple is fixed for this instance and is given in CORRECT VALUE below. Lowering it so the flag still applies is a WRONG repair.',
   defn='A review flag that exists only because a threshold held. If the threshold no longer holds the flag must be WITHDRAWN, not renumbered.',
   quantity="whether this chart carries a review flag",
   prose="The flag exists only while leader >= flag-multiple * chart median. If that "
         "stops holding, the flag must be withdrawn rather than renumbered.",
   expr="sv[0] >= t_flag * med",
   fn=lambda F, A, C, T: F['sv'][0] >= T[1] * F['med']),

 'textval_cross_rank': dict(
   presence='required',
   defn='Where this chart ranks among all charts by leader value.',
   quantity="where this chart ranks among all charts by leader value",
   prose="Collect every chart's largest value, sort them descending, and report this "
         "chart's 1-based position, out of the number of charts in the atlas.",
   expr="L = sorted(maxv for each chart, reverse=True); L.index(this.maxv) + 1",
   fn=lambda F, A, C, T: sorted((A[c]['maxv'] for c in A), reverse=True
                                ).index(F['maxv']) + 1),

 'textval_atlas_mean': dict(
   presence='required',
   defn='An atlas-wide sweep: the mean across every chart.',
   quantity="the atlas-wide mean of chart leaders",
   prose="Take each chart's largest value, average them, round to one decimal place.",
   expr="round(sum(L) / len(L), 1)",
   fn=lambda F, A, C, T: round(sum(A[c]['maxv'] for c in A) / len(A), 1)),

 'textval_atlas_third': dict(
   presence='required',
   fixed='It is the THIRD largest, not the second or fourth. Changing the rank so an old figure reads true again is a WRONG repair.',
   defn='An atlas-wide sweep: the third-largest chart leader.',
   quantity="the third-largest chart leader",
   prose="Sort every chart's largest value descending and take the third.",
   expr="L = sorted(..., reverse=True); L[2]",
   fn=lambda F, A, C, T: sorted((A[c]['maxv'] for c in A), reverse=True)[2]),

 'textval_atlas_spread': dict(
   presence='required',
   defn='An atlas-wide sweep: the spread between the largest and smallest leader.',
   quantity="the gap between the largest and smallest chart leader",
   prose="Largest chart-leader minus smallest chart-leader, rounded to one decimal place.",
   expr="round(L[0] - L[-1], 1)",
   fn=lambda F, A, C, T: round(sorted((A[c]['maxv'] for c in A), reverse=True)[0]
                               - sorted((A[c]['maxv'] for c in A), reverse=True)[-1], 1)),

 'textval_atlas_concentration': dict(
   presence='required',
   fixed='The comparison is over the FIVE largest chart leaders. Changing that five so an old percentage reads true again is a WRONG repair.',
   defn='An atlas-wide sweep: concentration of value across charts.',
   quantity="the share of the atlas total held by the five largest leaders",
   prose="Sum the five largest chart-leaders, divide by the sum of all chart-leaders, "
         "times 100, rounded to a whole percent.",
   expr="round(100.0 * sum(L[:5]) / sum(L))",
   fn=lambda F, A, C, T: round(100.0 * sum(sorted((A[c]['maxv'] for c in A),
                                                  reverse=True)[:5])
                               / sum(A[c]['maxv'] for c in A))),

 'textval_leader_margin': dict(
   presence='required',
   fixed='The margin is measured against the RUNNER-UP. Measuring it against the median, the mean or the total so an old percentage reads true again is a WRONG repair.',
   defn='The leader’s margin over the runner-up, as a percentage.',
   quantity="the leader's margin over the runner-up, as a percentage",
   prose="(largest - second largest) / second largest, times 100, rounded to a whole "
         "percent. The denominator is the RUNNER-UP, not the leader and not the total.",
   expr="round(100.0 * (sv[0] - sv[1]) / sv[1])",
   fn=lambda F, A, C, T: round(100.0 * (F['sv'][0] - F['sv'][1]) / F['sv'][1])),

 'textsem_superlative': dict(
   presence='required',
   defn='Prose asserting, in no fixed wording, who recorded the highest figure.',
   quantity="which entity recorded the highest figure in this chart",
   prose="The label of the row with the largest value, after the correction.",
   expr="max(rows, key=value)[label]",
   fn=lambda F, A, C, T: F['leader']),

 'textval_cross_ratio': dict(
   presence='required',
   fixed='The peer chart is fixed for this instance and is named in the sentence by its workstream code. Comparing against a DIFFERENT chart so an old multiple reads true again is a WRONG repair.',
   defn='This chart’s leader as a multiple of another named chart’s leader — a cross-chart comparison.',
   quantity="this chart's leader as a multiple of one named other chart's leader",
   prose="Divide this chart's largest value by the named peer chart's largest value and "
         "round to one decimal place. The peer is fixed per instance and is named in the "
         "sentence by its workstream code.",
   expr="round(this.maxv / peer.maxv, 1)   # peer = sorted(other chart ids)[len(atlas)//3]",
   fn=lambda F, A, C, T: round(
       F['maxv'] / A[sorted(c for c in A if c != C)[len(A) // 3]]['maxv'], 1)),

 'textval_atlas_leader_index': dict(
   presence='required',
   defn='The mean of every chart’s leader value — a cross-chart join.',
   quantity="the atlas-wide mean of chart leaders",
   prose="Take each chart's largest value, average them over the number of charts, round "
         "to one decimal place.",
   expr="round(sum(maxv for each chart) / len(atlas), 1)",
   fn=lambda F, A, C, T: round(sum(A[c]['maxv'] for c in A) / len(A), 1)),

 'textval_atlas_portfolio': dict(
   presence='required',
   fixed='The threshold is 10,000 exactly. Moving it so an old count reads true again is a WRONG repair.',
   defn='How many charts have a leader above a stated threshold.',
   quantity="how many charts have a leader above 10,000",
   prose="Count the charts whose largest value is strictly greater than 10000. The "
         "threshold is absolute, not relative to anything.",
   expr="sum(1 for c in atlas if c.maxv > 10000)",
   fn=lambda F, A, C, T: sum(1 for c in A if A[c]['maxv'] > 10000)),

 'textval_atlas_overview': dict(
   presence='required',
   defn='Two atlas-wide claims in one file: how many charts are catalogued, and the highest single value anywhere in the atlas.',
   quantity="the highest single value anywhere in the atlas",
   prose="The largest value anywhere in the atlas, the entity that records it and the "
         "chart it sits in. The same sentence also states how many charts are catalogued, "
         "which the correction does not change and which must stay as it was.",
   expr="top = max(atlas, key=maxv); (len(atlas), top.maxv, top.leader, top_id)",
   fn=lambda F, A, C, T: (lambda t: dict(charts=len(A), highest=A[t]['maxv'],
                                         recorded_by=A[t]['leader'], in_chart=t))(
       max(A, key=lambda c: A[c]['maxv']))),

 'textval_atlas_record_note': dict(
   presence='retirable',
   defn='A note that exists only because one entity held the atlas record. Once the record moves it must be rewritten for the new holder or retired; leaving the old claim standing is the failure.',
   quantity="which entity holds the highest single value anywhere in the atlas",
   prose="The leader label of whichever chart has the largest value in the atlas. This "
         "note exists ONLY because that entity held the record: if the record has passed "
         "to someone else the note must be rewritten for the new holder or retired, and "
         "leaving the old holder named is the failure.",
   expr="atlas_top = max(atlas, key=maxv); (atlas_top.leader, top_id, atlas_top.maxv)",
   fn=lambda F, A, C, T: (lambda t: dict(record_holder=A[t]['leader'], in_chart=t,
                                         value=A[t]['maxv']))(
       max(A, key=lambda c: A[c]['maxv']))),

 'textval_atlas_dashboard': dict(
   presence='required',
   defn='One row of a table built from every chart’s stats file: this chart’s leader, mean and verdict.',
   quantity="this chart's row in the dashboard table: its leader, mean and verdict",
   prose="One row per chart. The leader is the label of the largest value; the mean is the "
         "mean of all values rounded to one decimal place; the verdict is MAJORITY when "
         "more than 50%% of entries sit above that rounded mean, otherwise MINORITY.",
   expr="leader, round(mean,1), 'MAJORITY' if round(100*above/n) > 50 else 'MINORITY'",
   fn=lambda F, A, C, T: dict(leader=F['leader'], mean=F['mean'], verdict=F['verdict'])),

 'textsem_dominance': dict(
   presence='withdrawable',
   defn='A qualitative characterisation — whether one entry "dominates". Nothing in the workspace defines the word, so after the change the claim may have to be withdrawn rather than renumbered.',
   quantity="whether the named entity still dominates this chart",
   prose="Nothing in the workspace defines 'dominates'. The benchmark adopts an "
         "OPERATIONAL definition -- one demanding reading, not the only possible one -- "
         "under which the claim holds only if all four of these hold at once: the entity "
         "has the largest value, AND more than twice the runner-up, AND is in the top "
         "three, AND holds more than a tenth of the chart total. Corpus construction "
         "admits this site only when the correction turns all four from true to false "
         "together, so the verdict does not depend on which of them a reader has in mind. "
         "If it no longer holds the claim must be withdrawn -- there is no substitute "
         "figure.",
   expr="is_largest and v > 2*sv[1] and v in sv[:3] and v > sum(sv)/10",
   fn=lambda F, A, C, T: (F['sv'][0] > 2 * F['sv'][1]
                          and F['sv'][0] > sum(F['sv']) / 10.0)),
}


def atlas_post(exp):
    """Every chart's facts for this instance, with the correction applied.

    Built from source_post where the generator wrote it (the target chart, and any chart the
    edit touched) and from exp['values'] otherwise. Returns None if the instance does not
    carry enough to reconstruct the atlas, so verify() reports a gap instead of inventing one.
    """
    vals = exp.get('values') or {}
    if not vals:
        return None
    out = {}
    for cid, d in vals.items():
        out[cid] = chart([(k, float(v)) for k, v in d.items()])
    for rel, txt in (exp.get('source_post') or {}).items():
        m = re.match(r'data/([^/]+)/values\.csv$', rel)
        if not m:
            continue
        rows = [(l.rsplit(',', 1)[0], float(l.rsplit(',', 1)[1]))
                for l in txt.strip().split('\n')[1:] if l.strip()]
        if rows:
            out[m.group(1)] = chart(rows)
    return out


def value_for(site, exp):
    """The figure this claim should now carry, computed by its stated rule."""
    r = RULES.get(site)
    A = atlas_post(exp)
    if not r or not A:
        return None
    cid = exp.get('target')
    if cid not in A:
        return None
    T = tuple(exp.get('thresh') or (0, 0))      # (order-of-magnitude multiple, flag multiple)
    return r['fn'](A[cid], A, cid, T)


def _stated(gold_line):
    """Every number gold's sentence actually states."""
    return [float(x.replace(',', '')) for x in re.findall(r'\d[\d,]*\.?\d*', gold_line)]


def _renders_exactly(want, line):
    """Does the string we show the judge match a figure gold states, digit for digit?

    Substring matching is not enough: "1154.5" IS a substring of "1154.51", so a lossy
    renderer would pass a substring test. The rendered value has to equal one of gold's
    numbers as a token.
    """
    w = _fmt(want).replace(',', '')
    return any(t.replace(',', '') == w
               for t in re.findall(r'\d[\d,]*\.?\d*', line))


def verify(quiet=False, tasks='tasks/general/atlas-*'):
    """Every rule must reproduce what gold states, on every task it appears in.

    `tasks` is a glob of task folders: tasks/general/atlas-* (the default), tasks/health/h-*
    or tasks/rna_labels/b-*.
    """
    import grade_vis_atlas as GR
    ok, bad, gap = 0, [], 0
    for tj in sorted(glob.glob(os.path.join(REPO, tasks, 'task.json'))):
        inst = os.path.basename(os.path.dirname(tj))
        exp = GR._resolve(json.load(open(tj))['exp'])
        for site in sorted(set(exp['broken']) & set(RULES)):
            rel, k = GR.claim_line_index(site, exp)
            if rel is None or k is None:
                gap += 1
                continue
            gl = (GR._read(exp['gold_root'], rel) or '').split('\n')
            if k >= len(gl):
                gap += 1
                continue
            want = value_for(site, exp)
            if want is None:
                gap += 1
                continue
            if isinstance(want, bool):
                # A predicate: gold states it by asserting or negating the sentence.
                neg = bool(re.search(r'\bno\b|\bwithin\b|\bnot\b', gl[k], re.I))
                if want == (not neg):
                    ok += 1
                else:
                    bad.append((inst, site, 'predicate %s but gold reads %r' % (want, gl[k][:70])))
            elif isinstance(want, dict):
                miss = [f for f, v in want.items()
                        if not (str(v).lower() in gl[k].lower() if isinstance(v, str)
                                else any(abs(x - float(v)) < 0.51 for x in _stated(gl[k])))]
                if not miss:
                    ok += 1
                else:
                    bad.append((inst, site, 'fields %s absent from %r' % (miss, gl[k][:60])))
            elif isinstance(want, str):
                if want.lower() in gl[k].lower():
                    ok += 1
                else:
                    bad.append((inst, site, 'want %r not in %r' % (want, gl[k][:70])))
            else:
                # Two checks, because they fail differently. The numeric one allows a small
                # tolerance and would pass 1154.5 against gold's 1154.51, which would show the
                # judge a wrong figure. So the RENDERED string, the thing the judge actually
                # reads, must also appear in gold's sentence.
                if not any(abs(x - float(want)) < 0.51 for x in _stated(gl[k])):
                    bad.append((inst, site, 'rule gives %s, gold line %r'
                                % (want, gl[k][:70])))
                elif not _renders_exactly(want, gl[k]):
                    bad.append((inst, site, 'rendered %r is not the figure gold states: %r'
                                % (_fmt(want), gl[k][:70])))
                else:
                    ok += 1
    if not quiet:
        print('rules verified against gold: %d agree, %d disagree, %d not applicable'
              % (ok, len(bad), gap))
        for b in bad[:12]:
            print('   MISMATCH %-16s %-28s %s' % b)
    return ok, bad, gap




def _fmt(v):
    """Render a value for a reader WITHOUT losing precision.

    Every significant digit is kept. Rounding to one decimal place would show the judge
    1,154.5 for a median of 1154.51, and the judge would then fail a model that wrote the true
    value. Thousands separators are added for legibility.
    """
    if isinstance(v, int):
        return '{:,}'.format(v)
    if isinstance(v, float):
        if abs(v - round(v)) < 1e-9:
            return '{:,}'.format(int(round(v)))
        t = repr(v)                    # shortest form that round-trips; %f re-introduces
        if 'e' in t or 'E' in t:       # the binary artefact it was meant to hide
            t = ('%.10f' % v).rstrip('0').rstrip('.')
        ip, _, fp = t.partition('.')
        neg = ip.startswith('-')
        ip = '{:,}'.format(abs(int(ip)))
        return ('-' if neg else '') + ip + ('.' + fp if fp else '')
    return str(v)


def want_text(site, exp):
    """The rule's answer, written for a reader rather than for a comparison.

    A bare `False` tells the judge nothing it can check a sentence against, so a predicate is
    rendered with the comparison that settled it -- and with the fact that no substitute
    figure exists, which is the whole difficulty of these sites.
    """
    w = value_for(site, exp)
    if w is None:
        return None
    if isinstance(w, bool) and site == 'textsem_dominance':
        A = atlas_post(exp)
        F = A[exp['target']]
        return ('%s -- %s leads with %s; the runner-up is %s (twice that is %s) and the '
                'chart total is %s (a tenth is %s). "Dominates" holds only if EVERY reading '
                'holds at once. There is NO substitute figure: if it no longer holds the '
                'claim has to be withdrawn, not renumbered.'
                % ('THE CLAIM STILL HOLDS' if w else 'THE CLAIM NO LONGER HOLDS',
                   F['leader'], _fmt(F['sv'][0]), _fmt(F['sv'][1]), _fmt(2 * F['sv'][1]),
                   _fmt(sum(F['sv'])), _fmt(sum(F['sv']) / 10.0)))
    if isinstance(w, bool):
        A = atlas_post(exp)
        F = A[exp['target']]
        t = (exp.get('thresh') or (0, 0))[0 if site == 'textsem_ratio_threshold' else 1]
        return ('%s -- the leader is %s and %s x the chart median is %s x %s = %s, so the '
                'leader is %s that bar. There is NO replacement figure: if the claim no '
                'longer holds the sentence has to be negated or withdrawn, not renumbered.'
                % ('THE CLAIM HOLDS' if w else 'THE CLAIM NO LONGER HOLDS',
                   _fmt(F['sv'][0]), _fmt(t), _fmt(t), _fmt(F['med']), _fmt(t * F['med']),
                   'at or above' if w else 'below'))
    if isinstance(w, dict):
        return ', '.join('%s %s' % (k, _fmt(v) if isinstance(v, (int, float)) else v)
                         for k, v in w.items())
    if isinstance(w, str):
        return w
    if site.endswith(('top3', 'concentration')):
        return '%s%%' % _fmt(w)
    return _fmt(w)


if __name__ == '__main__':
    import argparse as _ap
    _a = _ap.ArgumentParser()
    _a.add_argument('--tasks', default='tasks/general/atlas-*',
                    help='glob of task folders, e.g. tasks/health/h-*')
    _o, _b, _g = verify(tasks=_a.parse_args().tasks)
    sys.exit(1 if _b else 0)
