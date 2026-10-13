"""BixBench-RNA: the derived layer sits on a real published RNA-seq experiment.

The VisText workspaces take their numbers from published charts, where the corrected item is a
cell of a bar chart. This module takes them from a **BixBench capsule**: the raw count matrix and
sample sheet of a published differential-expression study, downloaded from
`futurehouse/BixBench` on Hugging Face (Apache-2.0, ungated).

    CapsuleData-15ff11e5-.../counts_raw_unfiltered.csv   63,677 genes x 30 samples
    CapsuleData-15ff11e5-.../sample_layout.csv           10 conditions x 3 replicates
    CapsuleData-15ff11e5-.../ensg_to_gene_name.tsv       ENSG -> gene symbol

The correction is a mislabelled sample
--------------------------------------
The correction is not an edited number. It is a **mislabelled sample** -- the most common
correction a sequencing core actually issues, and one the capsule's own metadata file is
vulnerable to. Nothing in the counts changes. What changes is which replicate belongs to which
condition, and that propagates through group means into every fold change, every ranked gene
list, every count of responders and every conclusion drawn from them.

In the VisText workspaces an agent can in principle find the stale claims by searching for the
number it was told changed. Here **there is no such number**: the correction names a sample, and
no derived document mentions samples. Every stale claim has to be found by re-deriving.

What is real and what is generated
----------------------------------
REAL: the count matrix, the sample sheet, the gene symbols, the experiment (a cisplatin/CBD
combination study), and the whole computation -- CPM normalisation, expression filtering,
per-condition means, fold changes, ranking.

GENERATED: the derived prose layer, by the same pure functions the VisText workspaces use
(gen_vis_atlas). The capsule's own markdown is mostly FutureHouse template boilerplate, not
scientific narrative, so there is no human caption to harvest: the review caption is emitted
rather than harvested.

Ground truth is still exact: run the same derivation over the corrected sample sheet and every
figure follows.

    contrasts(counts, layout)  -> {contrast: [(gene, fold change), ...]}  the "charts"
    build_instance(...)        -> pre/post states for gen_vis_atlas to render
"""
import os, sys, csv, json, itertools, random

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import gen_vis_atlas as A

# The three capsule files are shipped in data/bixbench/; RB_BIXBENCH_CAPSULE
# points at another copy (for example the original CapsuleData-15ff11e5-... download).
CAPSULE = os.environ.get('RB_BIXBENCH_CAPSULE') or os.path.join(REPO, 'data', 'bixbench')

# Analysis parameters. They are a fixed specification and are stated in the workspace.
MIN_CPM = 1.0        # a gene counts as expressed at or above this many counts per million
MIN_SAMPLES = 3      # ...in at least this many samples
N_GENES = 18         # how many genes a contrast's ranked list carries


def load(capsule=CAPSULE):
    """The capsule, as plain Python. pandas is used for the matrix arithmetic only."""
    import pandas as pd
    counts = pd.read_csv(os.path.join(capsule, 'counts_raw_unfiltered.csv'), index_col=0)
    layout = pd.read_csv(os.path.join(capsule, 'sample_layout.csv'))
    # The sample sheet writes 1-1 and the count matrix writes 1_1. Joining on the wrong one
    # silently produces an empty intersection and a workspace of zeros.
    layout['col'] = layout['SampleID'].str.replace('-', '_', regex=False)
    missing = set(layout['col']) - set(counts.columns)
    if missing:
        raise ValueError('sample sheet names columns the matrix does not have: %s' % sorted(missing))
    syms = {}
    with open(os.path.join(capsule, 'ensg_to_gene_name.tsv')) as fh:
        r = csv.reader(fh, delimiter='\t')
        next(r, None)
        for row in r:
            if len(row) >= 2:
                syms[row[0]] = row[1]
    return counts, layout, syms


def expressed(counts):
    """Counts per million, restricted to genes expressed in at least MIN_SAMPLES samples.

    Library-size normalisation before filtering, which is the order every RNA-seq pipeline uses:
    filtering on raw counts would drop genes from deeply sequenced samples for being small
    rather than for being absent.
    """
    cpm = counts / counts.sum(axis=0) * 1e6
    return cpm[(cpm > MIN_CPM).sum(axis=1) >= MIN_SAMPLES]


def contrasts(cpm, layout, syms, n_genes=N_GENES):
    """Every pairwise contrast, as a ranked list of (gene symbol, fold change).

    Fold change is (mean of A + 1) / (mean of B + 1) so it is always positive and a gene that is
    absent in both conditions sits at 1.0 rather than dividing by zero. The +1 is a pseudocount
    and is part of the stated specification.
    """
    import pandas as pd
    grp = {g: layout.loc[layout.Group == g, 'col'].tolist()
           for g in sorted(layout.Group.unique())}
    means = pd.DataFrame({g: cpm[c].mean(axis=1) for g, c in grp.items()})
    out = {}
    for a, b in itertools.combinations(sorted(grp), 2):
        fc = (means[a] + 1) / (means[b] + 1)
        top = fc.sort_values(ascending=False).head(n_genes)
        rows = [(syms.get(g, g), round(float(v), 3)) for g, v in top.items()]
        # A duplicate gene symbol would give two rows the same label, which the grader reads as
        # one claim about two things.
        seen, uniq = set(), []
        for lbl, v in rows:
            if lbl in seen:
                continue
            seen.add(lbl)
            uniq.append((lbl, v))
        out['%s_vs_%s' % (a, b)] = uniq
    return out


def _unit(name):
    return 'fold change vs %s' % name.split('_vs_')[1].replace('_', ' ')


def _title(name):
    a, b = name.split('_vs_')
    return 'Top responding genes, %s versus %s' % (a.replace('_', ' '), b.replace('_', ' '))


def _caption(rows, name):
    """The review line. EMITTED, not harvested -- see the module docstring."""
    a, b = name.split('_vs_')
    lead, v = rows[0]
    return ('Across the genes expressed in this experiment, %s shows the largest response in '
            '%s relative to %s, at %.2f-fold.' % (lead, a.replace('_', ' '), b.replace('_', ' '), v))


def _chart(rows, name):
    """One contrast, in the shape gen_vis_atlas expects of a VisText series."""
    return dict(title=_title(name), caption=_caption(rows, name), rows=rows,
                xname=_unit(name), yname='gene', orient='h', img_id='bix-%s' % name)


def find_correction(counts, layout, syms, seed=0, n_charts=30):
    """Search for a (sample, wrong label) pair whose correction moves a contrast's top gene.

    Returns (candidates, cpm) where each candidate is one usable target contrast. The window is
    assembled around the target afterwards, in `build_instance`, rather than hoping the target
    happens to hold the workspace maximum -- the same construction gen_vis_target uses to build
    an atlas around a chosen series.

    The CPM matrix is computed once, outside the search: the correction relabels samples and
    does not change a single count.
    """
    cpm = expressed(counts)
    correct = contrasts(cpm, layout, syms)
    groups = sorted(layout.Group.unique())
    rng = random.Random(seed)
    order = list(layout.index)
    rng.shuffle(order)

    out = []
    for i in order:
        sid, true_g = layout.at[i, 'SampleID'], layout.at[i, 'Group']
        for wrong_g in groups:
            if wrong_g == true_g:
                continue
            # The SHIPPED sheet carries the error, so build it by writing the wrong label in;
            # the corrected sheet is the capsule's own.
            wrong = layout.copy()
            wrong.at[i, 'Group'] = wrong_g
            shipped = contrasts(cpm, wrong, syms)
            for target in shipped:
                if target not in correct:
                    continue
                s_rows, c_rows = shipped[target], correct[target]
                if s_rows[0][0] == c_rows[0][0]:
                    continue                       # the top gene did not change hands
                if len(s_rows) < 12 or len(c_rows) < 12:
                    continue
                if not (s_rows[0][1] > s_rows[1][1] > 0 and c_rows[0][1] > c_rows[1][1] > 0):
                    continue                       # a tie at the top is not a superlative
                out.append(dict(shipped=shipped, correct=correct, target=target,
                                sample=sid, wrong=wrong_g, true=true_g, wrong_layout=wrong))
    return out, cpm


def build_instance(found, n_charts=30, variant=0, seed=0):
    """Assemble pre/post states in the form `gen_vis_atlas` renders.

    The window is built AROUND the target: every peer's top fold change sits below the target's,
    so the target holds the workspace maximum and the cross-contrast aggregates depend on it; and
    at least one peer sits above the target's CORRECTED maximum, so the correction genuinely
    costs it that place. A peer must also be a true preservation site -- unchanged by the
    relabel -- or it would be a second, unannounced correction.

    The target is placed at a seeded position rather than at the head, because chart ids are
    assigned in pick order and heading the window would make it `c01` every time.
    """
    shipped, correct, target = found['shipped'], found['correct'], found['target']
    t_pre = shipped[target][0][1]
    t_post = correct[target][0][1]
    peers = [k for k in shipped
             if k != target
             and len(shipped[k]) >= 12
             and shipped[k] == correct.get(k)
             and shipped[k][0][1] > shipped[k][1][1] > 0
             and shipped[k][0][1] < t_pre]
    if len(peers) < n_charts - 1:
        return None, 'only %d unchanged contrasts rank below the target; need %d' % (
            len(peers), n_charts - 1)
    rng = random.Random(seed)
    rng.shuffle(peers)
    chosen = peers[:n_charts - 1]
    if not any(shipped[k][0][1] > t_post for k in chosen):
        # put one above the corrected maximum in deliberately, or the contrast keeps its place
        above = [k for k in peers if shipped[k][0][1] > t_post]
        if not above:
            return None, 'no unchanged contrast sits above the corrected maximum (%.3f)' % t_post
        chosen[-1] = above[0]
    at = rng.randrange(n_charts)
    names = chosen[:at] + [target] + chosen[at:]

    pre, post = {}, {}
    for i, nm in enumerate(names, 1):
        cid = 'c%02d' % i
        pre[cid] = dict(u=_chart(shipped[nm], nm), rows=shipped[nm],
                        f=A.chart_facts(shipped[nm]))
        rows = correct[nm] if nm == target else shipped[nm]
        post[cid] = dict(u=_chart(rows, nm), rows=rows, f=A.chart_facts(rows))
    tcid = 'c%02d' % (names.index(target) + 1)

    import gen_vis_target as G
    inst = dict(target=tcid, pre=pre, post=post, order=sorted(pre), mode='relabel',
                edits=[dict(kind='relabel', entity=found['sample'],
                            old=found['wrong'], new=found['true'])],
                contrast=target, sample=found['sample'])
    if not G.retarget_thresholds(inst):
        return None, 'no threshold the correction crosses'
    if G._count_collision(inst):
        return None, 'the superseded maximum renders as the chart count'
    A._TARGET[0] = tcid
    A._VARIANT[0] = variant
    A._ENTITY[0] = pre[tcid]['f']['leader']
    return inst, 'ok'
