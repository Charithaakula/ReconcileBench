"""A disk cache for judge verdicts, keyed on the exact question asked.

Caching makes a scored table reproducible: a re-run cannot move a row because the judge answered
differently the second time. The key is the full (system, user) pair, so a change to a prompt
invalidates exactly the entries that prompt produced.

    from jcache import ask_cached
    label = ask_cached(SYSTEM, user, r'"label"\\s*:\\s*"(A|B|C)"')
"""
import hashlib, json, os, re, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PATH = os.path.join(REPO, 'results', 'judge_cache.json')
_LOCK = threading.Lock()


def _load():
    if not hasattr(_load, 'd'):
        try:
            _load.d = json.load(open(PATH))
        except Exception:
            _load.d = {}
    return _load.d


def ask_cached(system, user, pattern, tries=3):
    """Return the first capture group of `pattern` in the judge's reply, or None."""
    key = hashlib.sha256(('%s\x00%s' % (system, user)).encode()).hexdigest()
    d = _load()
    if key in d:
        return d[key]
    sys.path.insert(0, HERE)
    import judge_claim as J
    out = None
    for _ in range(tries):
        _v, _r, raw = J._ask(system, user)
        m = re.search(pattern, raw or '')
        if m:
            out = m.group(1)
            break
    if out is not None:
        with _LOCK:
            d[key] = out
            os.makedirs(os.path.dirname(PATH), exist_ok=True)
            tmp = PATH + '.tmp'
            json.dump(d, open(tmp, 'w'))
            os.replace(tmp, PATH)
    return out
