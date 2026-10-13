"""Regression tests for the atlas.

Run: python3 -m pytest tests/ -q   (or: python3 tests/test_atlas.py)
"""
import csv, json


def _rows(cid):
    return [(r[0], float(r[1])) for r in
            list(csv.reader(open("data/%s/values.csv" % cid)))[1:]]


def test_leader_matches_source():
    rows = _rows('c10')
    assert max(rows, key=lambda r: r[1])[0] == 'Lombardy'


def test_leader_value():
    rows = _rows('c10')
    assert max(r[1] for r in rows) == 390331.2


if __name__ == "__main__":
    _f = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print("PASS", _name)
            except AssertionError as _e:
                _f += 1
                print("FAIL", _name, _e)
    raise SystemExit(1 if _f else 0)
