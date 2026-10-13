"""Classify the two criterion sentences of a prose criterion-revision episode.

In these episodes the review criteria change and the data do not, so the sentences that state
the order-of-magnitude multiple and the review-flag multiple must be rewritten with the new
multiples and the verdicts those imply. Each sentence the agent left is labelled:

    UPDATED    states the new multiple, with the verdict the new multiple implies
    UNCHANGED  still states the old multiple: the agent did not act
    WRONG      acted, but states the wrong multiple or the wrong verdict

The label comes from a judge given the multiples and the ratio, not from matching the reference
sentence, so the agent is free to reword. scorers/score_prose_criterion.py finds the two
sentences and calls classify().
"""
import os, sys, re

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SYSTEM = """A data workspace states two review criteria as multiples of a chart's median. Both
multiples have just been revised by the analysts. The chart's DATA did not change.

You are shown one sentence the agent left in the file, the OLD multiple, the NEW multiple, and
the chart's actual leader-to-median ratio. Decide what the sentence does.

  UPDATED    it states the NEW multiple, and the verdict it draws is the one the new multiple
             implies given the ratio. (ratio >= multiple means the claim/flag holds; ratio <
             multiple means it does not and the sentence must say so.)

  UNCHANGED  it still states the OLD multiple. The agent did not act on the revision.

  WRONG      it acted but got it wrong: a multiple that is neither the old nor the new one, or
             the new multiple with the verdict the ratio does not support.

Wording is free. Any phrasing that states the right multiple and the right verdict is UPDATED.

Reply with JSON only: {"reason": "<one clause>", "label": "UPDATED"|"UNCHANGED"|"WRONG"}"""

TMPL = """OLD multiple: {old}
NEW multiple: {new}
The chart's actual leader / median ratio: {ratio:.2f}
Therefore under the NEW multiple the claim {holds}.

THE SENTENCE THE AGENT LEFT
  {line}

What does this sentence do?"""

# Topic anchors, not phrasings: they find the sentence by what it is about, and the judge
# decides what it says. Matching a phrasing such as "The leading entry stands" would miss a
# correct negation like "The leading entry does **not** stand more than 10 times the chart
# median".
ORD_RE = re.compile(r'chart median', re.I)
FLAG_RE = re.compile(r'review flag', re.I)


def classify(line, old, new, ratio):
    from jcache import ask_cached
    user = TMPL.format(old=old, new=new, ratio=ratio,
                       holds='HOLDS' if ratio >= new else 'DOES NOT HOLD', line=line)
    return ask_cached(SYSTEM, user,
                      r'"label"\s*:\s*"(UPDATED|UNCHANGED|WRONG)"') or 'UNDECIDED'
