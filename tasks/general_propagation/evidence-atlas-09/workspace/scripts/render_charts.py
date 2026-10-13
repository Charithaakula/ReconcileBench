"""Regenerates every figure in figs/ from data/. Run after changing any source."""
import csv, math, os, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def nice_ceiling(v):
    k = math.floor(math.log10(v))
    for m in (1.0, 2.0, 2.5, 5.0, 10.0):
        c = m * 10 ** k
        if c >= v - 1e-12:
            return c
    return 10.0 ** (k + 1)


meta = {r["id"]: r for r in csv.DictReader(open("data/charts.csv"))}
for cid, m in sorted(meta.items()):
    rows = [(r[0], float(r[1])) for r in
            list(csv.reader(open("data/%s/values.csv" % cid)))[1:]]
    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=100)
    y = list(range(len(rows)))[::-1]
    ax.barh(y, [v for _, v in rows], color="#4c78a8")
    ax.set_yticks(y)
    ax.set_yticklabels([l for l, _ in rows], fontsize=7)
    ax.set_xlim(0, nice_ceiling(max(v for _, v in rows)))
    ax.set_xlabel(m["unit"], fontsize=8)
    ax.set_title(m["title"], fontsize=8)
    fig.tight_layout()
    fig.savefig("figs/%s.png" % cid, format="png", metadata={"Software": None})
    plt.close(fig)
