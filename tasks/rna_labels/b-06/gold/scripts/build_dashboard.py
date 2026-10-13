"""Rebuilds docs/dashboard.md from every analysis/<code>-stats.json.

The codename for each chart is in analysis/INDEX.md; the layout is flat, not nested.
"""
import csv, json, re
meta = {r["id"]: r for r in csv.DictReader(open("data/charts.csv"))}
code = {}
for line in open("analysis/INDEX.md"):
    m = re.match(r"\|\s*([a-z]{3}-\d+)\s*\|\s*(.+?)\s*\|", line)
    if m:
        for cid, r in meta.items():
            if r["title"].strip() == m.group(2):
                code[cid] = m.group(1)
out = ["# Chart dashboard", "", "| chart | leader | mean | status |", "|---|---|---|---|"]
for cid in sorted(meta):
    s = json.load(open("analysis/%s-stats.json" % code[cid]))
    out.append("| %s | %s | %s | %s |" % (cid, s["leader"], s["mean"], s["verdict"]))
open("docs/dashboard.md", "w").write("\n".join(out) + "\n")
