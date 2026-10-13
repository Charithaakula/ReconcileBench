#!/usr/bin/env python3
"""Recompute the current Cisplatin IC50 versus Untreated contrast from visible sources."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

MIN_CPM = 1.0
MIN_SAMPLES = 3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    capsule = root / "sources" / "capsule"
    with (capsule / "counts_raw_unfiltered.csv").open(newline="", encoding="utf-8") as handle:
        rows = csv.reader(handle)
        columns = next(rows)[1:]
        matrix = [(row[0], [float(value) for value in row[1:]]) for row in rows]
    with (capsule / "ensg_to_gene_name.tsv").open(newline="", encoding="utf-8") as handle:
        rows = csv.reader(handle, delimiter="\t")
        next(rows)
        symbols = {gene_id: symbol for gene_id, symbol, *_ in rows}
    layout = list(csv.DictReader((capsule / "sample_layout_base.csv").open(
        newline="", encoding="utf-8")))
    if (root / "sources" / "sample-sheet-record.json").exists():
        sample = json.loads((root / "sources" / "sample-sheet-record.json").read_text())
    else:
        sample = json.loads((root / "sources" / "transitions.json").read_text())["sample"]
    for row in layout:
        if row["SampleID"] == sample["id"]:
            row["Group"] = sample["group"]

    column_index = {name: index for index, name in enumerate(columns)}
    groups = defaultdict(list)
    for row in layout:
        groups[row["Group"]].append(row["SampleID"].replace("-", "_"))
    library_sizes = [sum(values[index] for _, values in matrix) for index in range(len(columns))]
    ranked = []
    for gene_id, values in matrix:
        cpm = [value / library_sizes[index] * 1e6 for index, value in enumerate(values)]
        if sum(value > MIN_CPM for value in cpm) < MIN_SAMPLES:
            continue
        means = {
            group: sum(cpm[column_index[column]] for column in group_columns) / len(group_columns)
            for group, group_columns in groups.items()
        }
        fold_change = (means["Cisplatin_IC50"] + 1) / (means["Untreated"] + 1)
        ranked.append((fold_change, gene_id))
    seen = set()
    for fold_change, gene_id in sorted(ranked, reverse=True):
        label = symbols.get(gene_id, gene_id)
        if label in seen:
            continue
        result = {
            "contrast": "Cisplatin_IC50_vs_Untreated",
            "corrected_group_members": len(groups[sample["group"]]),
            "leader_gene": label,
            "leader_fold_change": round(fold_change, 3),
        }
        break
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.write:
        target = root / "analysis" / ("sample-contrast.json" if
            (root / "analysis" / "sample-contrast.json").exists() else "current-computation.json")
        target.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
