"""VisText parsing with a pixel cross-check.

The flat `datatable` string is ambiguous: labels may contain numbers ("Dec 31, 2005",
"2005/06", "18-19"), so a naive "non-numeric tokens are the label, numeric token is the
value" scan silently mis-segments: on a date-labelled chart it captures the YEAR as the
value and drops the real value, and on every chart it absorbs the two column headers into the
first label.

Two further properties of the records:

  * **Orientation.** 47% of records are *horizontal* bars: the x-axis carries the numbers
    and the y-axis the categories, and the datatable row format is `<value> <label>`,
    reversed from the vertical case.
  * **The scenegraph is ground truth.** Every record ships a Vega scenegraph whose ticks
    give the pixel->value linear map and whose marks encode each value as a bar height
    (vertical), a bar width (horizontal) or a point position (line/area). So the value
    sequence can be recovered from pixels *independently of the string*, and the
    categorical tick list names every bar category.

A record is `usable` only when the string and the pixels describe the same numbers.

Data: https://vis.csail.mit.edu/vistext/tabular.zip  (+ scenegraphs.zip)
"""
import json, re

NUM = re.compile(r'-?\d+\.?\d*$')
_FMT = re.compile(r'^[$\u20ac\u00a3]?\s*(-?[\d,]*\.?\d+)\s*%?$')


def to_num(tok):
    """Tick labels are rendered, not raw: '1,000', '0.6%', '$5' are all numeric."""
    m = _FMT.match(tok.strip())
    if not m:
        return None
    try:
        return float(m.group(1).replace(',', ''))
    except ValueError:
        return None


# --------------------------------------------------------------------------- scenegraph

def parse_scenegraph(sg):
    """Flat scenegraph string -> dict, or None if it does not have the expected shape.

    Bar marks:        XY <x> <y> width <w> H <h> desc
    Line/area marks:  XY <x> <y> desc
    """
    try:
        return _parse_scenegraph(sg)
    except (ValueError, IndexError, TypeError):
        return None


def _parse_scenegraph(sg):
    toks = sg.split()
    try:
        i_xt, i_yt, i_mk = toks.index('xtick'), toks.index('ytick'), toks.index('marks')
    except ValueError:
        return None
    if not i_xt < i_yt < i_mk:
        return None

    def ticks(seg, axis):
        """"<axis> <px> val <label tokens...>" repeating -> [(px, label)]."""
        out, j = [], 0
        while j < len(seg):
            if seg[j] != axis or j + 2 >= len(seg) or seg[j + 2] != 'val':
                return None
            if not NUM.match(seg[j + 1]):     # some records carry a 'None' tick position
                return None
            px, k, lab = float(seg[j + 1]), j + 3, []
            while k < len(seg) and seg[k] != axis:
                lab.append(seg[k]); k += 1
            if not lab:
                return None
            out.append((px, ' '.join(lab)))
            j = k
        return out

    xt, yt = ticks(toks[i_xt + 1:i_yt], 'x'), ticks(toks[i_yt + 1:i_mk], 'y')
    if not xt or not yt:
        return None

    seg = toks[i_mk + 1:]
    if not seg:
        return None
    marktype, seg, marks, j = seg[0], seg[1:], [], 0
    while j < len(seg):
        if seg[j] != 'XY' or j + 2 >= len(seg):
            return None
        if not (NUM.match(seg[j + 1]) and NUM.match(seg[j + 2])):
            return None                   # a mark with a missing coordinate
        m = {'x': float(seg[j + 1]), 'y': float(seg[j + 2])}
        j += 3
        if j + 1 < len(seg) and seg[j] == 'width' and NUM.match(seg[j + 1]):
            m['width'] = float(seg[j + 1]); j += 2
        if j + 1 < len(seg) and seg[j] == 'H' and NUM.match(seg[j + 1]):
            m['H'] = float(seg[j + 1]); j += 2
        if j < len(seg) and seg[j] == 'desc':
            j += 1
        marks.append(m)
    if not marks:
        return None
    return {'xticks': xt, 'yticks': yt, 'marktype': marktype, 'marks': marks}


def _numeric(ticks):
    return all(to_num(v) is not None for _, v in ticks)


def orientation(sgd):
    """'v' = numeric y-axis (vertical bars, lines, areas); 'h' = numeric x-axis."""
    if _numeric(sgd['yticks']) and not _numeric(sgd['xticks']):
        return 'v'
    if _numeric(sgd['xticks']) and not _numeric(sgd['yticks']):
        return 'h'
    if _numeric(sgd['yticks']):          # both numeric: y carries the measure
        return 'v'
    return None


def _linear(ticks):
    """[(px, numeric-label)] -> (value_per_px, px_at_zero), or None if degenerate."""
    (p0, v0), (p1, v1) = ticks[0], ticks[-1]
    v0, v1 = to_num(v0), to_num(v1)
    if v0 is None or v1 is None:
        return None
    if p1 == p0:
        return None
    slope = (v1 - v0) / (p1 - p0)
    if slope == 0:
        return None
    return slope, p0 - v0 / slope


def pixel_series(sgd, orient):
    """-> [(tick_px, value)] recovered from the marks, or None.

    Vertical bars encode the value as height above the baseline, horizontal bars as
    width, lines/areas as the y coordinate of the point.
    """
    lin = _linear(sgd['xticks'] if orient == 'h' else sgd['yticks'])
    if not lin:
        return None
    slope, _ = lin

    ser = []
    for m in sgd['marks']:
        if orient == 'h':
            if 'width' not in m:
                return None
            ser.append((m['y'] + m.get('H', 0) / 2.0, m['width'] * slope))
        elif 'H' in m:
            ser.append((m['x'] + m.get('width', 0) / 2.0, m['H'] * -slope))
        else:
            (p0, v0) = sgd['yticks'][0]
            ser.append((m['x'], to_num(v0) + (m['y'] - p0) * slope))
    return ser


def close(a, b, tol=0.02, scale=0.0):
    """Pixel recovery carries ~3 significant figures.

    A purely relative test cannot compare against zero, and zero values are common
    (a series that starts at 0). `scale` is the magnitude of the series, giving the
    comparison an absolute floor proportional to the chart's own range.
    """
    if a == b:
        return True
    return abs(a - b) <= tol * max(abs(a), abs(b), 0.05 * abs(scale))


# --------------------------------------------------------------------------- datatable

def strip_header(dt, xname, yname):
    """-> (title, body-without-column-headers) or (None, None)."""
    if '<s>' not in dt:
        return None, None
    title, body = dt.split('<s>', 1)
    body = body.strip()
    xname, yname = (xname or '').strip(), (yname or '').strip()
    for head in (f'{xname} {yname}', f'{yname} {xname}', xname, yname):
        if head and body.startswith(head):
            return title.strip(), body[len(head):].strip()
    return title.strip(), body


def _segment_by_vocab(toks, vocab, value_first):
    """Bar charts: the categorical ticks name every bar, so segment on known labels.

    Longest-match, left to right. Each label must sit next to exactly one numeric token
    (after it when the row is `label value`, before it when `value label`).
    """
    maxlen = max(len(v.split()) for v in vocab)
    rows, i, pending_num = [], 0, None
    while i < len(toks):
        hit = None
        for n in range(min(maxlen, len(toks) - i), 0, -1):
            cand = ' '.join(toks[i:i + n])
            if cand in vocab:
                hit = (cand, n); break
        if hit:
            lab, n = hit
            if value_first:
                if pending_num is None:
                    return None
                rows.append((lab, pending_num)); pending_num = None
            else:
                if i + n >= len(toks) or not NUM.match(toks[i + n]):
                    return None
                rows.append((lab, float(toks[i + n]))); n += 1
            i += n
        elif NUM.match(toks[i]):
            if not value_first or pending_num is not None:
                return None
            pending_num = float(toks[i]); i += 1
        else:
            return None
    if pending_num is not None:
        return None
    return rows


def _segment_by_sequence(toks, expected, scale=0.0):
    """Line/area: no full label vocabulary, but the value sequence is known in x order.

    A numeric token closes the current row only when it matches the next expected value,
    so numeric label tokens (years) are absorbed into the label harmlessly.
    """
    rows, buf, i = [], [], 0
    for t in toks:
        if i < len(expected) and NUM.match(t) and close(float(t), expected[i], scale=scale):
            if not buf:
                return None
            rows.append((' '.join(buf), float(t))); buf = []; i += 1
        else:
            buf.append(t)
    if i != len(expected) or buf:
        return None
    return rows


# --------------------------------------------------------------------------- record

def usable(rec):
    """-> parsed record dict, or None if the string and the pixels cannot be reconciled."""
    try:
        return _usable(rec)
    except (ValueError, IndexError, KeyError, TypeError, ZeroDivisionError):
        return None


def _usable(rec):
    props = rec.get('L1_properties') or []
    if len(props) != 6:
        return None
    ctype, title, xname, yname, xscale, yscale = props

    sgd = parse_scenegraph(rec['scenegraph'])
    if not sgd:
        return None
    orient = orientation(sgd)
    if not orient:
        return None
    ser = pixel_series(sgd, orient)
    if not ser:
        return None

    t, body = strip_header(rec['datatable'], xname, yname)
    if body is None:
        return None
    toks = body.split()

    cat_ticks = sgd['yticks'] if orient == 'h' else sgd['xticks']
    if ctype == 'bar':
        vocab = {lab for _, lab in cat_ticks}
        rows = _segment_by_vocab(toks, vocab, value_first=(orient == 'h'))
    else:
        scale = max((abs(v) for _, v in ser), default=0.0)
        rows = _segment_by_sequence(toks, [v for _, v in sorted(ser, key=lambda p: p[0])],
                                    scale=scale)
    if not rows or len(rows) != len(ser):
        return None

    # ---- cross-check: every parsed value must match the pixel it was drawn as ----
    scale = max((abs(v) for _, v in ser), default=0.0)
    if ctype == 'bar':
        by_px = {round(px): v for px, v in ser}
        tick_px = {lab: px for px, lab in cat_ticks}
        for lab, val in rows:
            px = tick_px.get(lab)
            if px is None:
                return None
            near = min(by_px, key=lambda p: abs(p - px))
            if abs(near - px) > 3 or not close(by_px[near], val, scale=scale):
                return None
    else:
        for (lab, val), (_, pv) in zip(rows, sorted(ser, key=lambda p: p[0])):
            if not close(pv, val, scale=scale):
                return None

    return dict(caption_id=rec['caption_id'], img_id=rec['img_id'], ctype=ctype,
                orient=orient, title=title, xname=xname, yname=yname,
                xscale=xscale, yscale=yscale, rows=rows, sg=sgd,
                caption_L1=rec['caption_L1'], caption=rec['caption_L2L3'])


def load(path):
    return json.load(open(path))
