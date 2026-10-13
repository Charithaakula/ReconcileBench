#!/usr/bin/env python3
"""Build the BixBench-RNA mixed evidence/policy cases: tasks/rna_mixed/m-01 .. m-06.

Each case is a small RNA-seq project in which sample metadata and two lines of evidence feed a
contrast, candidate findings and the validation actions a written support policy licenses:

    m-01  sample 6-3 is relabelled; raw counts do not change
    m-02  evidence E1 is withdrawn for AHRR; E2 still supports it
    m-03  evidence E1 is withdrawn for CYP1A1; its last support lapses
    m-04  the policy raises the required independent supports from two to three
    m-05  the policy lowers the required supports from three to two
    m-06  all three kinds of transition in one project

Values come from the BixBench capsule (data/bixbench) through the facts recorded by
generators/select_rna_mixed.py. Each case is written as task.json (the turn and the scored
fields, each marked change or preserve), workspace/ and gold/.

    python generators/make_rna_mixed.py
    python generators/check_rna_mixed.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "bixbench"
CASES = ("m-01", "m-02", "m-03", "m-04", "m-05")
TREE = {"pre": "workspace", "post": "gold"}
E1 = "CBD_IC50_vs_Cisplatin_IC50"
E2 = "CBD_IC50_Serum_starvation_16h_vs_Cisplatin_IC50_Serum_starvation_16h"


def dump_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def dump_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pointer(value, selector: str):
    for token in selector.strip("/").split("/") if selector != "/" else []:
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def recompute_script() -> str:
    return '''#!/usr/bin/env python3
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
        rows = csv.reader(handle, delimiter="\\t")
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
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\\n"
    if args.write:
        target = root / "analysis" / ("sample-contrast.json" if
            (root / "analysis" / "sample-contrast.json").exists() else "current-computation.json")
        target.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
'''


def package_executable_capsule(root: Path, capsule: Path) -> None:
    destination = root / "sources" / "capsule"
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("counts_raw_unfiltered.csv", "ensg_to_gene_name.tsv"):
        # Preserve content while using repository-standard LF line endings.
        data = (capsule / name).read_bytes().replace(b"\r\n", b"\n")
        (destination / name).write_bytes(data)
    rows = list(csv.DictReader((capsule / "sample_layout.csv").open(
        encoding="utf-8", newline="")))
    for row in rows:
        if row["SampleID"] == "6-3":
            row["Group"] = "OVERRIDDEN_BY_SOURCE_RECORD"
    with (destination / "sample_layout_base.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    dump_text(root / "analysis" / "recompute_contrast.py", recompute_script())


def evidence(audit: dict, candidate: str, e1_current: bool = True) -> list[dict]:
    rows = []
    for evidence_id, contrast in (("E1", E1), ("E2", E2)):
        obs = audit["registered_evidence"][candidate][contrast]
        rows.append({
            "id": evidence_id,
            "contrast": contrast,
            "candidate": candidate,
            "rank": obs["rank"],
            "fold_change": obs["fold_change"],
            "qualifies": obs["qualifies"],
            "status": "CURRENT" if evidence_id != "E1" or e1_current else "WITHDRAWN_QC",
        })
    return rows


def support_state(rows: list[dict], minimum_supports: int) -> dict:
    active = [row for row in rows if row["status"] == "CURRENT" and row["qualifies"]]
    status = "SUPPORTED" if len(active) >= minimum_supports else "NOT_ESTABLISHED"
    return {
        "active_support_count": len(active),
        "active_evidence_ids": [row["id"] for row in active],
        "status": status,
        "action": "RUN_VALIDATION" if status == "SUPPORTED" else "HOLD",
    }


def policy(version: str, minimum_supports: int) -> dict:
    return {
        "effective_version": version,
        "minimum_supports": minimum_supports,
        "qualification": {
            "meaning": "numerical qualification of the contrast result; independent of current/withdrawn status",
            "maximum_rank": 10,
            "minimum_fold_change": 2.0,
        },
        "evidence_status_vocabulary": {
            "CURRENT": "eligible to contribute active support",
            "WITHDRAWN_QC": "withdrawn after quality-control failure; ineligible for active support",
        },
        "active_support_rule": "status is CURRENT and numerical qualifies is true",
        "independence_rule": "condition-specific sample sets must be disjoint",
        "decision_rule": {"SUPPORTED": "RUN_VALIDATION", "NOT_ESTABLISHED": "HOLD"},
        "contrast_target_rule": (
            "after a sample-label correction, the current top-ranked gene with fold change "
            "at least 2.0 has current finding SUPPORTED, is the validation target, and licenses "
            "RUN_VALIDATION"
        ),
        "history_rule": "dated decisions retain the policy effective when made",
    }


def base_state(case_id: str, audit: dict, phase: str) -> dict:
    assert phase in {"pre", "post"}
    common = {
        "case_id": case_id,
        "phase": phase,
        "unaffected": {"candidate": "GAPDH", "status": "REFERENCE_CONTROL"},
        "archive": {
            "policy_version": "P0",
            "finding": "SUPPORTED",
            "action": "RUN_VALIDATION",
            "dated": "2026-08-15",
        },
    }
    if case_id == "m-01":
        reclass = audit["sample_reclassification"]
        post = phase == "post"
        leader = reclass["post_leader"] if post else reclass["pre_leader"]
        group = reclass["corrected_group"] if post else reclass["shipped_group"]
        common.update({
            "kind": "sample_reclassification",
            "event": (
                "Sample 6-3 is corrected from Cisplatin_IC50 to "
                "Cisplatin_IC50_Serum_starvation_16h. Raw counts do not change."
            ),
            "sample": {"id": "6-3", "group": group, "raw_counts_sha256": "UNCHANGED_COUNTS"},
            "analysis": {
                "contrast": reclass["contrast"],
                "corrected_group_members": 3 if post else 4,
                "leader_gene": leader["gene"],
                "leader_fold_change": leader["fold_change"],
            },
            "finding": {"candidate": leader["gene"], "status": "SUPPORTED"},
            "action": {"candidate": leader["gene"], "operation": "RUN_VALIDATION"},
            "policy": policy("P0", 1),
            "evidence": evidence(audit, "AHRR"),
        })
        return common

    candidate = "AHRR" if case_id in {"m-02", "m-04", "m-05"} else "CYP1A1"
    if case_id in {"m-02", "m-03"}:
        current = phase == "pre"
        minimum = 1
        event = f"Evidence E1 is withdrawn after QC failure for {candidate}; E2 is unchanged."
        version = "P0"
    elif case_id == "m-04":
        current = True
        minimum = 2 if phase == "pre" else 3
        version = "P0" if phase == "pre" else "P1"
        event = "Current policy changes from two required independent supports to three; evidence is fixed."
    else:
        current = True
        minimum = 3 if phase == "pre" else 2
        version = "P0" if phase == "pre" else "P1"
        event = "Current policy changes from three required independent supports to two; evidence is fixed."
    rows = evidence(audit, candidate, e1_current=current)
    derived = support_state(rows, minimum)
    common.update({
        "kind": "evidence_withdrawal" if case_id in {"m-02", "m-03"} else "policy_change",
        "event": event,
        "sample": {"id": "6-3", "group": audit["sample_reclassification"]["corrected_group"],
                   "raw_counts_sha256": "UNCHANGED_COUNTS"},
        "policy": policy(version, minimum),
        "evidence": rows,
        "analysis": {
            "candidate": candidate,
            "active_support_count": derived["active_support_count"],
            "e1_qualifies": rows[0]["qualifies"],
            "e2_qualifies": rows[1]["qualifies"],
        },
        "finding": {"candidate": candidate, "status": derived["status"]},
        "action": {"candidate": candidate, "operation": derived["action"]},
    })
    return common


def visible_policy_text() -> str:
    return """# Candidate policy

- The `qualifies` field records only numerical qualification: the candidate is in the contrast's
  top ten and its fold change is at least 2.0. Withdrawing evidence does not change its recorded
  rank, fold change, or numerical `qualifies` value.
- Evidence status uses the complete vocabulary `CURRENT` and `WITHDRAWN_QC`. Evidence withdrawn
  after a quality-control failure must be recorded as `WITHDRAWN_QC`.
- Active support requires both `status == CURRENT` and `qualifies == true`.
- Supports are independent only when their condition-specific sample sets are disjoint.
- The effective policy's `minimum_supports` determines `SUPPORTED` versus `NOT_ESTABLISHED`.
- `SUPPORTED` licenses `RUN_VALIDATION`; `NOT_ESTABLISHED` licenses `HOLD`.
- After a sample-label correction, the current top-ranked contrast gene with fold change at least
  2.0 has current finding `SUPPORTED`, is the validation target, and licenses `RUN_VALIDATION`.
- Dated decisions retain the policy version effective when they were made.
"""


def render(state: dict, root: Path, capsule: Path | None = None) -> None:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    dump_text(root / "README.md", """# Persistent RNA-seq project

Keep current derived records semantically consistent with authoritative sources and policy.
Preserve dated history and unrelated controls. Do not edit files under `archive/`.
""")
    dump_text(root / "standards/candidate-policy.md", visible_policy_text())
    dump_json(root / "standards/candidate-policy.json", state["policy"])
    dump_json(root / "sources/sample-sheet-record.json", state["sample"])
    dump_json(root / "sources/evidence-status.json", {"records": state["evidence"]})
    dump_json(root / "sources/effective-policy.json", state["policy"])
    dump_json(root / "analysis/current-computation.json", state["analysis"])

    if state["kind"] == "sample_reclassification":
        relations = {
            "ranked_candidates": [state["analysis"]["leader_gene"], "AHRR", "CYP1A1"],
            "active_evidence_ids": ["sample-6-3", state["analysis"]["contrast"]],
            "validation_target": state["analysis"]["leader_gene"],
        }
        bars = [(state["analysis"]["leader_gene"], state["analysis"]["leader_fold_change"])]
    else:
        active = [row for row in state["evidence"] if row["status"] == "CURRENT" and row["qualifies"]]
        relations = {
            "ranked_candidates": [state["finding"]["candidate"]],
            "active_evidence_ids": [row["id"] for row in active],
            "support_join": [f"{row['id']}:{row['contrast']}" for row in active],
        }
        bars = [(row["id"], row["fold_change"] or 0.0) for row in active]
    dump_json(root / "results/current-relations.json", relations)
    dump_json(root / "findings/current-finding.json", state["finding"])
    dump_json(root / "decisions/validation-queue.json", state["action"])
    dump_json(root / "archive/dated-decision.json", state["archive"])
    dump_json(root / "controls/unaffected-reference.json", state["unaffected"])

    bar_nodes = "".join(
        f'<rect x="20" y="{20 + index * 28}" width="{round(value * 18, 3)}" height="18" />'
        f'<text x="25" y="{34 + index * 28}">{label}:{value}</text>'
        for index, (label, value) in enumerate(bars)
    )
    dump_text(root / "figures/candidate-summary.svg",
              f'<svg xmlns="http://www.w3.org/2000/svg" width="520" height="180">{bar_nodes}</svg>')
    dump_text(root / "manuscript/results.md", (
        f"# Current result\n\nCandidate: {state['finding']['candidate']}\n\n"
        f"Finding: {state['finding']['status']}\n\n"
        f"Licensed action: {state['action']['operation']}\n"
    ))
    if state["kind"] == "sample_reclassification":
        if capsule is None:
            raise ValueError("sample-reclassification fixtures require --capsule")
        package_executable_capsule(root, capsule)


def manifest_for(case_id: str, pre_root: Path, post_root: Path) -> list[dict]:
    """The scored fields of a standalone case, each with its starting and reference value."""
    if case_id == "m-01":
        source = ("sources/sample-sheet-record.json", "/group")
        computations = [
            ("group_membership", "/corrected_group_members"),
            ("contrast_leader", "/leader_gene"),
            ("contrast_fold_change", "/leader_fold_change"),
        ]
        relations = [
            ("ranked_candidates", "results/current-relations.json", "/ranked_candidates"),
            ("validation_target", "results/current-relations.json", "/validation_target"),
            ("candidate_figure", "figures/candidate-summary.svg", "sha256"),
        ]
    else:
        source = (("sources/evidence-status.json", "/records/0/status")
                  if case_id in {"m-02", "m-03"}
                  else ("sources/effective-policy.json", "/minimum_supports"))
        computations = [
            ("active_support_count", "/active_support_count"),
            ("e1_qualification", "/e1_qualifies"),
            ("e2_qualification", "/e2_qualifies"),
        ]
        relations = [
            ("active_evidence_ids", "results/current-relations.json", "/active_evidence_ids"),
            ("support_join", "results/current-relations.json", "/support_join"),
            ("candidate_figure", "figures/candidate-summary.svg", "sha256"),
        ]

    fields = [{"id": "source_transition", "role": "direct",
               "file": source[0], "selector": source[1]}]
    for field_id, selector in computations:
        fields.append({"id": field_id, "role": "C1",
                       "file": "analysis/current-computation.json", "selector": selector})
    for field_id, file_name, selector in relations:
        fields.append({"id": field_id, "role": "C2",
                       "file": file_name, "selector": selector})
    fields.extend([
        {"id": "current_finding", "role": "C3",
         "file": "findings/current-finding.json", "selector": "/"},
        {"id": "licensed_action", "role": "C3",
         "file": "decisions/validation-queue.json", "selector": "/"},
        {"id": "dated_finding", "role": "protected",
         "file": "archive/dated-decision.json", "selector": "/finding"},
        {"id": "dated_action", "role": "protected",
         "file": "archive/dated-decision.json", "selector": "/action"},
        {"id": "unaffected_control", "role": "protected",
         "file": "controls/unaffected-reference.json", "selector": "/status"},
    ])
    for field in fields:
        for phase, root in (("pre", pre_root), ("post", post_root)):
            if field["selector"] == "sha256":
                field[phase] = sha256(root / field["file"])
            else:
                value = json.loads((root / field["file"]).read_text())
                field[phase] = pointer(value, field["selector"])
        field["operation"] = "change" if field["pre"] != field["post"] else "preserve"
    return fields


def write_task(case_root: Path, case_id: str, kind: str, event: str, prompt: str,
               fields: list[dict]) -> None:
    dump_json(case_root / "task.json", {
        "id": case_id,
        "probe": "RNA_MIXED",
        "arm": kind,
        "event": event,
        "turns": [prompt.rstrip() + "\n"],
        "fields": fields,
    })


def build_compound(audit: dict, root: Path, capsule: Path | None) -> None:
    # The compound applies the sample correction, shared E1 withdrawal, and 2->3 policy change.
    pre_states = {case: base_state(case, audit, "pre") for case in CASES}
    post_states = {case: base_state(case, audit, "post") for case in CASES}
    for phase, states in (("pre", pre_states), ("post", post_states)):
        target = root / TREE[phase]
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        dump_text(target / "README.md", """# Compound RNA-seq project

Reconcile all current project records after the authoritative transitions. Preserve archives and
unaffected controls. Rules are visible under `standards/`; downstream files are not named here.
""")
        dump_text(target / "standards/candidate-policy.md", visible_policy_text())
        evidence_status = {
            row["id"]: row["status"] for row in states["m-02"]["evidence"]
        }
        dump_json(target / "sources/transitions.json", {
            "sample": states["m-01"]["sample"],
            "evidence_status": evidence_status,
            "policy": states["m-04"]["policy"],
        })
        dump_json(target / "analysis/sample-contrast.json", states["m-01"]["analysis"])
        candidate_supports = {}
        candidates = {}
        for candidate_case in ("m-02", "m-03"):
            candidate = states[candidate_case]["finding"]["candidate"]
            rows = [dict(row, status=evidence_status[row["id"]])
                    for row in states[candidate_case]["evidence"]]
            derived = support_state(rows, states["m-04"]["policy"]["minimum_supports"])
            candidate_supports[candidate] = {
                "records": rows,
                "active_support_count": derived["active_support_count"],
                "active_evidence_ids": derived["active_evidence_ids"],
            }
            candidates[candidate] = derived
        dump_json(target / "analysis/candidate-supports.json", candidate_supports)
        dump_json(target / "results/candidate-states.json", candidates)
        dump_json(target / "findings/current-findings.json",
                  {name: value["status"] for name, value in candidates.items()})
        dump_json(target / "decisions/validation-queue.json",
                  {name: value["action"] for name, value in candidates.items()})
        dump_json(target / "archive/dated-decisions.json", {
            "AHRR": pre_states["m-04"]["archive"],
            "CYP1A1": pre_states["m-03"]["archive"],
        })
        dump_json(target / "controls/unaffected-reference.json", states["m-01"]["unaffected"])
        dump_text(target / "figures/project-summary.svg", (
            '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="200">'
            + "".join(f'<text x="20" y="{30+i*30}">{name}:{value["status"]}</text>'
                      for i, (name, value) in enumerate(sorted(candidates.items()))) + '</svg>'
        ))
        dump_text(target / "manuscript/results.md", "# Current findings\n\n" + "\n".join(
            f"- {name}: {value['status']}; {value['action']}"
            for name, value in sorted(candidates.items())
        ))
        dump_text(target / "project/handoff.md", (
            f"Validation target: {states['m-01']['finding']['candidate']}\n\n"
            + "\n".join(f"{name}: {value['action']}" for name, value in sorted(candidates.items()))
        ))
        if capsule is None:
            raise ValueError("compound fixtures require --capsule")
        package_executable_capsule(target, capsule)

    # The compound manifest de-duplicates shared descendants at the semantic-field level. It is
    # intentionally not the arithmetic sum of the standalone manifests.
    specifications = [
        ("sample_group", "direct", "sources/transitions.json", "/sample/group"),
        ("e1_status", "direct", "sources/transitions.json", "/evidence_status/E1"),
        ("minimum_supports", "direct", "sources/transitions.json", "/policy/minimum_supports"),
        ("group_membership", "C1", "analysis/sample-contrast.json", "/corrected_group_members"),
        ("contrast_leader", "C1", "analysis/sample-contrast.json", "/leader_gene"),
        ("contrast_fold_change", "C1", "analysis/sample-contrast.json", "/leader_fold_change"),
        ("ahrr_support_count", "C1", "analysis/candidate-supports.json", "/AHRR/active_support_count"),
        ("cyp1a1_support_count", "C1", "analysis/candidate-supports.json", "/CYP1A1/active_support_count"),
        ("ahrr_active_evidence", "C2", "analysis/candidate-supports.json", "/AHRR/active_evidence_ids"),
        ("cyp1a1_active_evidence", "C2", "analysis/candidate-supports.json", "/CYP1A1/active_evidence_ids"),
        ("project_figure", "C2", "figures/project-summary.svg", "sha256"),
        ("ahrr_finding", "C3", "findings/current-findings.json", "/AHRR"),
        ("cyp1a1_finding", "C3", "findings/current-findings.json", "/CYP1A1"),
        ("ahrr_action", "C3", "decisions/validation-queue.json", "/AHRR"),
        ("cyp1a1_action", "C3", "decisions/validation-queue.json", "/CYP1A1"),
        ("manuscript_state", "C3", "manuscript/results.md", "sha256"),
        ("project_handoff", "C3", "project/handoff.md", "sha256"),
        ("dated_decisions", "protected", "archive/dated-decisions.json", "sha256"),
        ("unaffected_control", "protected", "controls/unaffected-reference.json", "/status"),
        ("fixed_policy_text", "protected", "standards/candidate-policy.md", "sha256"),
    ]
    fields = []
    for field_id, role, file_name, selector in specifications:
        field = {"id": field_id, "role": role, "file": file_name, "selector": selector}
        for phase in ("pre", "post"):
            path = root / TREE[phase] / file_name
            field[phase] = (sha256(path) if selector == "sha256"
                            else pointer(json.loads(path.read_text()), selector))
        field["operation"] = "change" if field["pre"] != field["post"] else "preserve"
        fields.append(field)
    event = ("Sample 6-3 is relabelled, evidence E1 is withdrawn for every candidate, and the "
             "policy raises the required supports from two to three.")
    write_task(root, "m-06", "compound", event, COMPOUND_PROMPT, fields)


COMPOUND_PROMPT = """Apply all three authoritative transitions below.

1. Sample 6-3 is corrected from Cisplatin_IC50 to
   Cisplatin_IC50_Serum_starvation_16h. Raw counts do not change.
2. Evidence E1 is withdrawn after quality-control failure for every current candidate finding.
   Evidence E2 remains current and its numerical measurements do not change.
3. Current policy P1 replaces P0 and raises minimum_supports from 2 to 3. Evidence measurements and
   dated decisions under P0 do not change.

Reconcile the complete current workspace so every semantic dependency is consistent. Preserve
dated history and unrelated controls. Do not create new files.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, default=DATA / "rna_mixed_selection.json",
                        help="capsule facts written by generators/select_rna_mixed.py")
    parser.add_argument("--capsule", type=Path, default=DATA,
                        help="directory holding the three BixBench capsule files")
    parser.add_argument("--output", type=Path, default=REPO / "tasks" / "rna_mixed")
    args = parser.parse_args()
    audit = json.loads(args.selection.read_text(encoding="utf-8"))
    assert audit["validation"] == "PASS"
    assert audit["capsule_files"] == {"genes": 63677, "samples": 30, "conditions": 10}
    args.output.mkdir(parents=True, exist_ok=True)

    for case_id in CASES:
        case_root = args.output / case_id
        if case_root.exists():
            shutil.rmtree(case_root)
        pre, post = base_state(case_id, audit, "pre"), base_state(case_id, audit, "post")
        render(pre, case_root / "workspace", args.capsule)
        render(post, case_root / "gold", args.capsule)
        prompt = (post["event"] + "\n\nReconcile the complete current workspace."
                  " Preserve dated history and unrelated controls. Do not create new files.\n")
        write_task(case_root, case_id, post["kind"], post["event"], prompt,
                   manifest_for(case_id, case_root / "workspace", case_root / "gold"))
    compound = args.output / "m-06"
    if compound.exists():
        shutil.rmtree(compound)
    build_compound(audit, compound, args.capsule)
    print(f"Built {len(CASES) + 1} cases in {args.output}")


if __name__ == "__main__":
    main()
