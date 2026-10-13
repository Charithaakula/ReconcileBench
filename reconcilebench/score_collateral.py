"""Damage to files a correction should never have touched.

Used for the already-applied (no-op) episodes, whose correct end state is the reference
(gold/), which there equals the starting workspace. Files are compared by content: line endings
and trailing whitespace are normalised (see score_revert.sha), because ordinary tooling writes
LF where the fixtures carry CRLF.

    collateral   a prose, data or code file the reference leaves as shipped that the agent
                 changed anyway: the workspace now says something the reference does not
    regenerated  a figure the agent re-rendered without needing to; it plots data that did
                 not change, so it is counted separately and never as damage
    deleted      a file the reference keeps that the agent removed

scorers/score_noop.py applies score_one to every episode.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from score_revert import tree

# README.md is excluded: appending to it does not change any derived claim.
FIGEXT = {'.png', '.svg', '.jpg', '.jpeg', '.pdf'}
EXCLUDE = {'README.md'}


def score_one(ep, base):
    ws = tree(os.path.join(base, 'workspace'))
    gd = tree(os.path.join(base, 'gold'))
    got = tree(ep)
    should_move = {r for r in ws if r in gd and ws[r] != gd[r]}
    frozen = [r for r in ws if r not in should_move and r not in EXCLUDE]
    moved = [r for r in frozen if r in got and got[r] != ws[r]]
    collateral = sorted(r for r in moved if os.path.splitext(r)[1] not in FIGEXT)
    regen = sorted(r for r in moved if os.path.splitext(r)[1] in FIGEXT)
    deleted = sorted(r for r in frozen if r not in got)
    repaired = sum(1 for r in should_move if got.get(r) == gd[r])
    nfig = sum(1 for r in frozen if os.path.splitext(r)[1] in FIGEXT)
    return dict(should_move=len(should_move), repaired=repaired, frozen=len(frozen),
                collateral=collateral, regen=regen, deleted=deleted, nfig=nfig)
