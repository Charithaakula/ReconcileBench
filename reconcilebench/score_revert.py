"""Score a retraction episode: did the workspace come back to where it started?

The correction is issued and then withdrawn, so a perfectly maintained workspace is identical to
the one the agent was given. The reference is therefore the shipped tree itself: no generator
run, no judge.

  restored     of the files the correction should have touched (those that differ between
               the shipped workspace and gold), how many came back to their shipped content
  residue      files still carrying the withdrawn correction
  third_state  files the correction touched that are now neither shipped nor corrected
  collateral   files that were never supposed to change and differ from shipped
  deleted      shipped files that are gone

scorers/score_retraction.py applies score_one to every episode.
"""
import os, hashlib


def sha(p):
    """Hash of the file's CONTENT, not its bytes.

    Line endings and trailing whitespace are normalised first. The fixtures carry CRLF in
    places; an agent that rewrites a file through ordinary tooling emits LF, and a raw byte
    comparison would report a perfectly restored file as a third state.
    """
    b = open(p, 'rb').read()
    try:
        t = b.decode('utf-8')
    except UnicodeDecodeError:
        return hashlib.sha256(b).hexdigest()          # binary: compare bytes
    t = t.replace('\r\n', '\n').replace('\r', '\n')
    t = '\n'.join(line.rstrip() for line in t.split('\n')).strip()
    return hashlib.sha256(t.encode()).hexdigest()


def tree(root):
    out = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            rel = os.path.relpath(p, root)
            if rel.startswith('.git') or '/__pycache__/' in '/' + rel:
                continue
            try:
                out[rel] = sha(p)
            except OSError:
                pass
    return out


def score_one(epdir, base):
    """base is the base instance dir: workspace/ is the start state, gold/ the corrected one."""
    ws = tree(os.path.join(base, 'workspace'))
    gd = tree(os.path.join(base, 'gold'))
    got = tree(epdir)

    # the files a correct reconciliation would have touched, and must then have untouched
    should_move = {r for r in ws if r in gd and ws[r] != gd[r]}
    restored = sum(1 for r in should_move if got.get(r) == ws[r])
    residue = sorted(r for r in should_move if got.get(r) == gd[r])
    other = sorted(r for r in should_move if r in got and got[r] not in (ws[r], gd[r]))
    collateral = sorted(r for r in ws
                        if r not in should_move and r in got and got[r] != ws[r])
    missing = sorted(r for r in ws if r not in got)
    return dict(should_move=len(should_move), restored=restored,
                residue=residue, third_state=other,
                collateral=collateral, deleted=missing)
