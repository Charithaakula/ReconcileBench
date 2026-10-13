#!/usr/bin/env python3
"""Derive the capsule facts the BixBench-RNA mixed cases are built from.

Reads the three BixBench capsule files (data/bixbench), computes the contrasts the cases use,
asserts the values the case design depends on, and writes data/bixbench/rna_mixed_selection.json,
the input of generators/make_rna_mixed.py.

    python generators/select_rna_mixed.py
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


MIN_CPM = 1.0
MIN_SAMPLES = 3
N_GENES = 18


def read_layout(path: Path):
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    return [
        {"sample": row["SampleID"], "col": row["SampleID"].replace("-", "_"), "group": row["Group"]}
        for row in rows
    ]


def read_symbols(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        rows = csv.reader(handle, delimiter="\t")
        next(rows)
        return {gene_id: symbol for gene_id, symbol, *_ in rows}


def read_counts(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        rows = csv.reader(handle)
        header = next(rows)
        columns = header[1:]
        matrix = [(row[0], [float(value) for value in row[1:]]) for row in rows]
    return columns, matrix


def contrasts(columns, matrix, layout, symbol_map, requested):
    column_index = {name: index for index, name in enumerate(columns)}
    groups = defaultdict(list)
    for row in layout:
        if row["col"] not in column_index:
            raise ValueError(f"sample column missing from count matrix: {row['col']}")
        groups[row["group"]].append(row["col"])

    column_sums = [sum(values[index] for _, values in matrix) for index in range(len(columns))]
    ranked = {name: [] for name in requested}
    for gene_id, values in matrix:
        cpm = [value / column_sums[index] * 1e6 for index, value in enumerate(values)]
        if sum(value > MIN_CPM for value in cpm) < MIN_SAMPLES:
            continue
        means = {
            group: sum(cpm[column_index[column]] for column in group_columns) / len(group_columns)
            for group, group_columns in groups.items()
        }
        for name in requested:
            left, right = name.split("_vs_", 1)
            ranked[name].append(((means[left] + 1) / (means[right] + 1), gene_id))

    output = {}
    for name, candidates in ranked.items():
        rows, seen = [], set()
        for value, gene_id in sorted(candidates, key=lambda item: item[0], reverse=True):
            label = symbol_map.get(gene_id, gene_id)
            if label in seen:
                continue
            seen.add(label)
            rows.append((label, round(value, 3)))
            if len(rows) == N_GENES:
                break
        output[name] = rows
    return output, dict(groups)


def observation(rows, gene):
    for index, (label, value) in enumerate(rows, 1):
        if label == gene:
            return {"rank": index, "fold_change": value, "qualifies": index <= 10 and value >= 2.0}
    return {"rank": None, "fold_change": None, "qualifies": False}


def main():
    parser = argparse.ArgumentParser()
    data = Path(__file__).resolve().parents[1] / "data" / "bixbench"
    parser.add_argument("--capsule", type=Path, default=data,
                        help="directory holding the three BixBench capsule files")
    parser.add_argument("--output", type=Path, default=data / "rna_mixed_selection.json")
    args = parser.parse_args()

    reclass_contrast = "Cisplatin_IC50_vs_Untreated"
    evidence = [
        "CBD_IC50_vs_Cisplatin_IC50",
        "CBD_IC50_Serum_starvation_16h_vs_Cisplatin_IC50_Serum_starvation_16h",
    ]
    requested = [reclass_contrast, *evidence]
    columns, matrix = read_counts(args.capsule / "counts_raw_unfiltered.csv")
    layout = read_layout(args.capsule / "sample_layout.csv")
    symbols = read_symbols(args.capsule / "ensg_to_gene_name.tsv")
    post, groups = contrasts(columns, matrix, layout, symbols, requested)
    wrong_layout = [dict(row) for row in layout]
    for row in wrong_layout:
        if row["sample"] == "6-3":
            row["group"] = "Cisplatin_IC50"
    pre, _ = contrasts(columns, matrix, wrong_layout, symbols, requested)
    facts = {
        "capsule_files": {
            "genes": len(matrix),
            "samples": len(columns),
            "conditions": len(groups),
        },
        "sample_reclassification": {
            "sample": "6-3",
            "shipped_group": "Cisplatin_IC50",
            "corrected_group": "Cisplatin_IC50_Serum_starvation_16h",
            "contrast": reclass_contrast,
            "pre_leader": {"gene": pre[reclass_contrast][0][0], "fold_change": pre[reclass_contrast][0][1]},
            "post_leader": {"gene": post[reclass_contrast][0][0], "fold_change": post[reclass_contrast][0][1]},
        },
        "registered_evidence": {
            "contrasts": evidence,
            "sample_sets_disjoint": set(groups[evidence[0].split("_vs_")[0]] + groups[evidence[0].split("_vs_")[1]]).isdisjoint(
                set(groups[evidence[1].split("_vs_")[0]] + groups[evidence[1].split("_vs_")[1]])
            ),
            "AHRR": {name: observation(post[name], "AHRR") for name in evidence},
            "CYP1A1": {name: observation(post[name], "CYP1A1") for name in evidence},
        },
    }

    expected = {
        "pre": ("NR4A3", 14.446),
        "post": ("ENSG00000258486", 2.852),
        "ahrr": [(1, 3.360, True), (8, 3.522, True)],
        "cyp1a1": [(2, 3.039, True), (None, None, False)],
    }
    assert (facts["sample_reclassification"]["pre_leader"]["gene"], facts["sample_reclassification"]["pre_leader"]["fold_change"]) == expected["pre"]
    assert (facts["sample_reclassification"]["post_leader"]["gene"], facts["sample_reclassification"]["post_leader"]["fold_change"]) == expected["post"]
    assert facts["registered_evidence"]["sample_sets_disjoint"] is True
    for gene, key in (("AHRR", "ahrr"), ("CYP1A1", "cyp1a1")):
        observed = [
            (facts["registered_evidence"][gene][name]["rank"], facts["registered_evidence"][gene][name]["fold_change"], facts["registered_evidence"][gene][name]["qualifies"])
            for name in evidence
        ]
        assert observed == expected[key], (gene, observed, expected[key])

    facts["validation"] = "PASS"
    rendered = json.dumps(facts, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
