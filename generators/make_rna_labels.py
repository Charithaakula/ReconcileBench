"""Rebuild the BixBench-RNA condition-label tasks (tasks/rna_labels/b-01 .. b-06) from task.json.

Each task.json records the text of every graded file in the starting workspace (exp.shipped), the
corrected sources (exp.source_post) and the figures' sha256. This script regenerates both trees
from those records, the BixBench capsule (data/bixbench) and the generator
(reconcilebench/gen_bixbench.py with the atlas renderer it feeds):

  1. Check that data/bixbench/sample_layout.csv is the corrected sample sheet every task records,
     and that each task's starting sheet differs from it only in the mislabelled library.
  2. Re-run gen_bixbench's derivation (load -> expressed -> contrasts) on the true sheet and on the
     mislabelled one, and build the starting and corrected chart states as
     gen_bixbench.build_instance does, using the contrasts in data/charts.csv order.
  3. Pick the thresholds (checked against exp.thresh) and the prose variant whose narrative
     reproduces the recorded text.
  4. workspace/ = the rendered starting atlas (which adds the figures and scripts the record does
     not carry), with every recorded text file written over it, plus the count matrix and gene
     map under data/. Figures are re-rendered with the workspace's own scripts/render_charts.py.
  5. gold/ = the workspace with the corrected derived layer and the corrected sources.

CSV files the generator writes with csv.writer (data/charts.csv, data/<cid>/values.csv and the
sample sheet) are written with CRLF line endings, as in the released tasks; --lf-csv writes them
with LF. The grader reads text mode and is indifferent.

    python generators/make_rna_labels.py [--ids b-01,b-02] [--lf-csv]

RB_RENDER_PYTHON selects the interpreter that renders the figures; matplotlib 3.10.7 reproduces
the shipped PNGs byte for byte.
"""
import sys as _sys; _sys.dont_write_bytecode = True
import argparse, csv, hashlib, io, json, os, re, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFESTS = os.path.join(REPO, 'tasks', 'rna_labels')   # <id>/task.json
VENV_PY = os.environ.get('RB_RENDER_PYTHON') or sys.executable
CAPSULE = os.path.join(REPO, 'data', 'bixbench')
IDS = ['b-0%d' % i for i in range(1, 7)]
MANIFEST_BYTES = {}
CRLF_CSV = re.compile(r'^data/(charts\.csv|sample_layout\.csv|c\d+/values\.csv)$')

sys.path.insert(0, os.path.join(REPO, 'reconcilebench'))
import gen_vis_atlas as A          # noqa: E402
import gen_vis_target as G         # noqa: E402
import gen_bixbench as B           # noqa: E402


def sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def build_png(root, script='scripts/render_charts.py'):
    """gen_vis.build_png with the configured renderer. matplotlib 3.10.7 reproduces the
    shipped VisText figures byte for byte."""
    r = subprocess.run([VENV_PY, script], cwd=root, capture_output=True, text=True)
    return r.returncode == 0, r.stderr


A.build_png = build_png


def read_text(root, rel):
    """How the grader (and the manifest) reads a file: universal newlines."""
    return open(os.path.join(root, rel), encoding='utf-8', errors='replace').read()


def write_text(root, rel, txt, crlf):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if crlf and CRLF_CSV.match(rel):
        txt = txt.replace('\r\n', '\n').replace('\n', '\r\n')
    with open(p, 'w', encoding='utf-8', newline='') as fh:
        fh.write(txt)


def normalise_csv_endings(root, crlf):
    for dp, _, fs in os.walk(root):
        for fn in fs:
            rel = os.path.relpath(os.path.join(dp, fn), root)
            if CRLF_CSV.match(rel):
                write_text(root, rel, read_text(root, rel), crlf)


# ----------------------------------------------------------------------------- capsule

def check_capsule(manifests):
    """The capsule's sample sheet is the corrected sheet every task records, and each task's
    starting sheet differs from it only in the mislabelled library."""
    posts = {t: m['exp']['source_post']['data/sample_layout.csv'] for t, m in manifests.items()}
    assert len(set(posts.values())) == 1, 'the corrected sample sheets disagree across tasks'
    truth = next(iter(posts.values()))
    assert open(os.path.join(CAPSULE, 'sample_layout.csv'), encoding='utf-8', newline='').read() \
        == truth, 'data/bixbench/sample_layout.csv is not the corrected sample sheet'
    assert len(truth.splitlines()) == 31
    for t, m in manifests.items():
        shipped = m['exp']['shipped']['data/sample_layout.csv'].splitlines()
        d = [(a, b) for a, b in zip(shipped, truth.splitlines()) if a != b]
        ml = m['exp']['mislabel']
        assert len(d) == 1 and d[0][0].split(',')[1:] == [ml['sample'], ml['shipped']] \
            and d[0][1].split(',')[1:] == [ml['sample'], ml['corrected']], (t, d)
    return dict(counts_sha=sha(os.path.join(CAPSULE, 'counts_raw_unfiltered.csv')),
                genes_sha=sha(os.path.join(CAPSULE, 'ensg_to_gene_name.tsv')),
                layout_sha=sha(os.path.join(CAPSULE, 'sample_layout.csv')))


# ---------------------------------------------------------------------------- instance

def rows_csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(['label', 'value'])
    w.writerows(rows)
    return buf.getvalue()


def make_instance(m, cpm, layout, syms, correct):
    """gen_bixbench.build_instance, with the window read from the manifest instead of searched."""
    exp = m['exp']
    ml = exp['mislabel']
    wrong = layout.copy()
    idx = wrong.index[wrong.SampleID == ml['sample']]
    assert len(idx) == 1 and wrong.at[idx[0], 'Group'] == ml['corrected']
    wrong.at[idx[0], 'Group'] = ml['shipped']
    shipped = B.contrasts(cpm, wrong, syms)
    by_title = {B._title(k): k for k in shipped}
    charts = list(csv.DictReader(io.StringIO(exp['shipped']['data/charts.csv'])))
    names = [by_title[r['title']] for r in charts]
    assert [r['id'] for r in charts] == ['c%02d' % i for i in range(1, len(names) + 1)]
    target = exp['contrast']
    tcid = 'c%02d' % (names.index(target) + 1)
    assert tcid == exp['target'], (tcid, exp['target'])
    pre, post = {}, {}
    for i, nm in enumerate(names, 1):
        cid = 'c%02d' % i
        pre[cid] = dict(u=B._chart(shipped[nm], nm), rows=shipped[nm],
                        f=A.chart_facts(shipped[nm]))
        rows = correct[nm] if nm == target else shipped[nm]
        post[cid] = dict(u=B._chart(rows, nm), rows=rows, f=A.chart_facts(rows))
    checks = dict(
        pre_values_match=all(rows_csv(pre[c]['rows']) == exp['shipped']['data/%s/values.csv' % c]
                             for c in pre),
        post_target_matches=rows_csv(post[tcid]['rows'])
        == exp['source_post']['data/%s/values.csv' % tcid],
        peers_unchanged=all(shipped[n] == correct[n] for n in names if n != target),
        values_match_exp=all(dict(post[c]['rows']) == exp['values'][c] for c in post),
    )
    inst = dict(target=tcid, pre=pre, post=post, order=sorted(pre), mode='relabel',
                edits=[dict(kind='relabel', entity=ml['sample'], old=ml['shipped'],
                            new=ml['corrected'])],
                contrast=target, sample=ml['sample'])
    assert G.retarget_thresholds(inst), 'no threshold the correction crosses'
    checks['thresh_match'] = list(A._THRESH) == list(exp['thresh'])
    A._TARGET[0] = tcid
    A._ENTITY[0] = pre[tcid]['f']['leader']
    return inst, checks


def derived_mismatches(inst, exp, variant):
    """Render the derived layer only (no figures) and list manifest files it does not
    reproduce."""
    A._VARIANT[0] = variant
    tmp = tempfile.mkdtemp(prefix='bixvar_')
    try:
        for s in ('data', 'figs', 'analysis', 'docs', 'tests'):
            os.makedirs(os.path.join(tmp, s), exist_ok=True)
        A._write_sources(tmp, inst['pre'])
        A._write_derived(tmp, inst['pre'])
        open(os.path.join(tmp, 'analysis/revision-log.md'), 'w').write(
            A.revision_log(inst['pre'], inst['target']))
        bad = []
        for rel, txt in exp['shipped'].items():
            if rel.endswith('.png'):
                continue
            p = os.path.join(tmp, rel)
            if os.path.exists(p) and read_text(tmp, rel) != txt:
                bad.append(rel)
        return bad
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------------------- build

def build_one(tid, m, cpm, layout, syms, correct, crlf):
    exp = m['exp']
    dst = os.path.join(MANIFESTS, tid)
    ws, gold = os.path.join(dst, 'workspace'), os.path.join(dst, 'gold')
    rep = dict(id=tid, target=exp['target'], contrast=exp['contrast'])

    inst, checks = make_instance(m, cpm, layout, syms, correct)
    rep.update(checks)
    per_var = {v: derived_mismatches(inst, exp, v) for v in (0, 1, 2)}
    variant = min(per_var, key=lambda v: len(per_var[v]))
    rep['variant'] = variant
    rep['variant_mismatch_counts'] = {v: len(x) for v, x in per_var.items()}
    rep['generator_mismatches'] = per_var[variant]   # manifest files the generator does not reproduce
    A._VARIANT[0] = variant

    # -- workspace: the generator's tree, then the manifest's text on top of it
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    r, log = A.render_pre(inst, ws)
    assert r, log
    gen_text = {rel: read_text(ws, rel) for rel in exp['shipped']
                if not rel.endswith('.png') and os.path.exists(os.path.join(ws, rel))}
    rep['generator_only_files'] = sorted(
        os.path.relpath(os.path.join(dp, f), ws) for dp, _, fs in os.walk(ws) for f in fs
        if os.path.relpath(os.path.join(dp, f), ws) not in exp['shipped'])
    rep['manifest_only_files'] = sorted(rel for rel in exp['shipped']
                                        if not os.path.exists(os.path.join(ws, rel)))
    rep['generator_differs_from_manifest'] = sorted(
        rel for rel, t in gen_text.items() if t != exp['shipped'][rel])
    for rel, txt in exp['shipped'].items():
        if not rel.endswith('.png'):
            write_text(ws, rel, txt, crlf)
    for fn in ('counts_raw_unfiltered.csv', 'ensg_to_gene_name.tsv'):
        shutil.copyfile(os.path.join(CAPSULE, fn), os.path.join(ws, 'data', fn))
    ok, log = build_png(ws, 'scripts/render_charts.py')
    assert ok, log
    rep['ws_png'] = {rel: sha(os.path.join(ws, rel)) == h
                     for rel, h in exp['shipped'].items() if rel.endswith('.png')}

    # -- gold: the corrected derived layer, then the recorded corrected sources on top
    shutil.copytree(ws, gold)
    A.perfect(inst, gold)
    for rel, txt in exp['source_post'].items():
        write_text(gold, rel, txt, crlf)
    normalise_csv_endings(gold, crlf)
    normalise_csv_endings(ws, crlf)
    ok, log = build_png(gold, 'scripts/render_charts.py')
    assert ok, log
    rep['gold_png_match'] = sha(os.path.join(gold, 'figs/%s.png' % exp['target'])) == exp['gold_png']
    rep['ws_target_png_match'] = sha(os.path.join(ws, 'figs/%s.png' % exp['target'])) == exp['shipped_png']
    rep['gold_source_post_match'] = {rel: read_text(gold, rel) == txt
                                     for rel, txt in exp['source_post'].items()}

    # -- task.json: unchanged, byte for byte
    open(os.path.join(dst, 'task.json'), 'wb').write(MANIFEST_BYTES[tid])
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ids', default=','.join(IDS))
    ap.add_argument('--lf-csv', action='store_true',
                    help='write exp.shipped CSVs verbatim (LF) instead of the CRLF the '
                         'original csv.writer-based builder produced')
    a = ap.parse_args()
    ids = [x.strip() for x in a.ids.split(',') if x.strip()]
    for t in IDS:
        MANIFEST_BYTES[t] = open(os.path.join(MANIFESTS, t, 'task.json'), 'rb').read()
    manifests = {t: json.loads(MANIFEST_BYTES[t]) for t in IDS}
    print(json.dumps(dict(capsule=check_capsule(manifests), crlf_csv=not a.lf_csv)), flush=True)
    counts, layout, syms = B.load(CAPSULE)
    cpm = B.expressed(counts)
    correct = B.contrasts(cpm, layout, syms)
    for tid in ids:
        rep = build_one(tid, manifests[tid], cpm, layout, syms, correct, not a.lf_csv)
        print(json.dumps({k: v for k, v in rep.items() if k != 'ws_png'}), flush=True)
        print('  workspace PNGs matching task.json: %d/%d' % (sum(rep['ws_png'].values()),
                                                              len(rep['ws_png'])), flush=True)


if __name__ == '__main__':
    main()
