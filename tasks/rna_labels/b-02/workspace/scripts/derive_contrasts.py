"""Rebuild data/<contrast>/values.csv from the count matrix and the sample sheet.

Run after any change to data/sample_layout.csv. The analysis parameters are fixed and are
recorded in notes/analysis-plan.md; this script is the executable form of that note.

Deliberately standard library only. An earlier version used pandas, and the episode environment
does not have it -- so the derivation the workspace depends on could not be run at all, and the
task was unsatisfiable for a reason that had nothing to do with reconciling anything.
"""
import csv, itertools, os

MIN_CPM, MIN_SAMPLES, N_GENES = 1.0, 3, 18

with open("data/counts_raw_unfiltered.csv", newline="") as fh:
    r = csv.reader(fh)
    cols = next(r)[1:]
    genes, mat = [], []
    for row in r:
        genes.append(row[0].strip('"'))
        mat.append([float(x) for x in row[1:]])

lib = [0.0] * len(cols)
for row in mat:
    for j, v in enumerate(row):
        lib[j] += v

# counts per million, by library size, before any filtering
cpm = [[(v / lib[j] * 1e6 if lib[j] else 0.0) for j, v in enumerate(row)] for row in mat]
keep = [i for i, row in enumerate(cpm) if sum(1 for v in row if v > MIN_CPM) >= MIN_SAMPLES]

syms = {}
with open("data/ensg_to_gene_name.tsv") as fh:
    next(fh, None)
    for line in fh:
        p = line.rstrip("
").split("	")
        if len(p) >= 2:
            syms[p[0]] = p[1]

idx = {c: j for j, c in enumerate(cols)}
groups = {}
with open("data/sample_layout.csv", newline="") as fh:
    for rec in csv.DictReader(fh):
        groups.setdefault(rec["Group"], []).append(idx[rec["SampleID"].replace("-", "_")])

means = {}
for g, js in groups.items():
    means[g] = [sum(cpm[i][j] for j in js) / len(js) for i in keep]

index = {rec["title"]: rec["id"] for rec in csv.DictReader(open("data/charts.csv"))}
for a, b in itertools.combinations(sorted(groups), 2):
    title = "Top responding genes, %s versus %s" % (a.replace("_", " "), b.replace("_", " "))
    cid = index.get(title)
    if not cid:
        continue
    fc = [((means[a][k] + 1) / (means[b][k] + 1), genes[i]) for k, i in enumerate(keep)]
    fc.sort(key=lambda p: -p[0])
    rows, seen = [], set()
    for v, g in fc:
        lbl = syms.get(g, g)
        if lbl in seen:
            continue
        seen.add(lbl)
        rows.append((lbl, round(v, 3)))
        if len(rows) == N_GENES:
            break
    os.makedirs("data/%s" % cid, exist_ok=True)
    with open("data/%s/values.csv" % cid, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["label", "value"])
        w.writerows(rows)
    print("wrote data/%s/values.csv  (%s)" % (cid, title))
