#!/usr/bin/env python3
"""Check the BixBench-RNA mixed cases (tasks/rna_mixed) for construction errors.

Every check is derived from the visible policy and the structured state: each case's starting
workspace and reference must each be internally consistent, the packaged contrast script must
reproduce the recorded contrast, the scored fields must match both trees, and the starting
workspace must fail the reference checks that the reference passes.

    python generators/check_rna_mixed.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
TREE = {"pre": "workspace", "post": "gold"}
STANDALONES = tuple(f"m-{index:02d}" for index in range(1, 6))
COMPOUND = "m-06"
EXPECTED_ROLES = {"direct": 1, "C1": 3, "C2": 3, "C3": 2, "protected": 3}
EXPECTED_C3_OPERATIONS = {
    "m-01": ["change", "change"],
    "m-02": ["preserve", "preserve"],
    "m-03": ["change", "change"],
    "m-04": ["change", "change"],
    "m-05": ["change", "change"],
}
FORBIDDEN_PROMPT_PATHS = (
    "analysis/", "results/", "findings/", "decisions/", "figures/", "manuscript/",
    "project/handoff",
)
CAPSULE_INPUTS = (
    "sources/capsule/counts_raw_unfiltered.csv",
    "sources/capsule/ensg_to_gene_name.tsv",
    "sources/capsule/sample_layout_base.csv",
    "analysis/recompute_contrast.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pointer(value, selector: str):
    if selector == "/":
        return value
    for token in selector.strip("/").split("/"):
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def observed_value(root: Path, field: dict):
    path = root / field["file"]
    if field["selector"] == "sha256":
        return digest(path)
    return pointer(read_json(path), field["selector"])


def require(condition: bool, message: str, checks: list[str]) -> None:
    if not condition:
        raise AssertionError(message)
    checks.append(message)


def expected_svg(bars: list[tuple[str, float]]) -> str:
    nodes = "".join(
        f'<rect x="20" y="{20 + index * 28}" width="{round(value * 18, 3)}" height="18" />'
        f'<text x="25" y="{34 + index * 28}">{label}:{value}</text>'
        for index, (label, value) in enumerate(bars)
    )
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="520" height="180">{nodes}</svg>\n'


def validate_standalone_semantics(case_root: Path, case_id: str, phase: str,
                                  selection: dict, checks: list[str]) -> None:
    root = case_root / TREE[phase]
    policy = read_json(root / "sources/effective-policy.json")
    visible_policy = read_json(root / "standards/candidate-policy.json")
    analysis = read_json(root / "analysis/current-computation.json")
    finding = read_json(root / "findings/current-finding.json")
    action = read_json(root / "decisions/validation-queue.json")
    relations = read_json(root / "results/current-relations.json")

    if case_id == "m-01":
        event = selection["sample_reclassification"]
        expected_group = event["shipped_group"] if phase == "pre" else event["corrected_group"]
        expected_leader = event["pre_leader"] if phase == "pre" else event["post_leader"]
        sample = read_json(root / "sources/sample-sheet-record.json")
        require(sample["group"] == expected_group,
                f"{case_id}/{phase}: sample group follows authoritative phase", checks)
        require(analysis["leader_gene"] == expected_leader["gene"] and
                analysis["leader_fold_change"] == expected_leader["fold_change"],
                f"{case_id}/{phase}: executable contrast leader matches capsule selection", checks)
        require(relations["ranked_candidates"][0] == analysis["leader_gene"] and
                relations["validation_target"] == analysis["leader_gene"],
                f"{case_id}/{phase}: rank and validation target follow contrast leader", checks)
        require(finding == {"candidate": analysis["leader_gene"], "status": "SUPPORTED"},
                f"{case_id}/{phase}: complete finding targets current leader", checks)
        require(action == {"candidate": analysis["leader_gene"], "operation": "RUN_VALIDATION"},
                f"{case_id}/{phase}: complete action targets current leader", checks)
        executed = json.loads(subprocess.check_output(
            [sys.executable, str(root / "analysis/recompute_contrast.py")], text=True
        ))
        require(executed == analysis,
                f"{case_id}/{phase}: packaged executable reproduces complete contrast record",
                checks)
        bars = [(analysis["leader_gene"], analysis["leader_fold_change"])]
    else:
        evidence = read_json(root / "sources/evidence-status.json")["records"]
        require(visible_policy["evidence_status_vocabulary"] == {
                    "CURRENT": "eligible to contribute active support",
                    "WITHDRAWN_QC": (
                        "withdrawn after quality-control failure; ineligible for active support"
                    ),
                }, f"{case_id}/{phase}: complete evidence-status vocabulary is visible", checks)
        require(visible_policy["active_support_rule"] ==
                "status is CURRENT and numerical qualifies is true",
                f"{case_id}/{phase}: active-support rule is visible", checks)
        require("independent of current/withdrawn status" in
                visible_policy["qualification"]["meaning"],
                f"{case_id}/{phase}: numerical qualification is distinguished from status",
                checks)
        active = [row for row in evidence if row["status"] == "CURRENT" and row["qualifies"]]
        expected_status = ("SUPPORTED" if len(active) >= policy["minimum_supports"]
                           else "NOT_ESTABLISHED")
        expected_action = "RUN_VALIDATION" if expected_status == "SUPPORTED" else "HOLD"
        require(analysis["active_support_count"] == len(active),
                f"{case_id}/{phase}: support count derives from current qualifying evidence", checks)
        require(analysis["e1_qualifies"] == evidence[0]["qualifies"] and
                analysis["e2_qualifies"] == evidence[1]["qualifies"],
                f"{case_id}/{phase}: qualification flags match evidence records", checks)
        require(relations["active_evidence_ids"] == [row["id"] for row in active],
                f"{case_id}/{phase}: active evidence relation is synchronized", checks)
        require(relations["support_join"] ==
                [f"{row['id']}:{row['contrast']}" for row in active],
                f"{case_id}/{phase}: support join is synchronized", checks)
        require(finding == {"candidate": analysis["candidate"], "status": expected_status},
                f"{case_id}/{phase}: finding follows visible policy", checks)
        require(action == {"candidate": analysis["candidate"], "operation": expected_action},
                f"{case_id}/{phase}: action follows visible decision rule", checks)
        bars = [(row["id"], row["fold_change"] or 0.0) for row in active]

    require((root / "figures/candidate-summary.svg").read_text(encoding="utf-8") ==
            expected_svg(bars), f"{case_id}/{phase}: SVG is regenerated from current state", checks)
    expected_prose = (
        f"# Current result\n\nCandidate: {finding['candidate']}\n\n"
        f"Finding: {finding['status']}\n\nLicensed action: {action['operation']}\n"
    )
    require((root / "manuscript/results.md").read_text(encoding="utf-8") == expected_prose,
            f"{case_id}/{phase}: manuscript is synchronized", checks)


def validate_compound_semantics(case_root: Path, phase: str, checks: list[str]) -> None:
    root = case_root / TREE[phase]
    source = read_json(root / "sources/transitions.json")
    supports = read_json(root / "analysis/candidate-supports.json")
    states = read_json(root / "results/candidate-states.json")
    findings = read_json(root / "findings/current-findings.json")
    actions = read_json(root / "decisions/validation-queue.json")
    minimum = source["policy"]["minimum_supports"]
    executed = json.loads(subprocess.check_output(
        [sys.executable, str(root / "analysis/recompute_contrast.py")], text=True
    ))
    require(executed == read_json(root / "analysis/sample-contrast.json"),
            f"{COMPOUND}/{phase}: packaged executable reproduces complete contrast record", checks)

    for candidate in ("AHRR", "CYP1A1"):
        records = supports[candidate]["records"]
        require(all(row["status"] == source["evidence_status"][row["id"]] for row in records),
                f"{COMPOUND}/{phase}: {candidate} evidence status is visible upstream", checks)
        active = [row for row in records if row["status"] == "CURRENT" and row["qualifies"]]
        expected_status = "SUPPORTED" if len(active) >= minimum else "NOT_ESTABLISHED"
        expected_action = "RUN_VALIDATION" if expected_status == "SUPPORTED" else "HOLD"
        require(supports[candidate]["active_support_count"] == len(active) and
                supports[candidate]["active_evidence_ids"] == [row["id"] for row in active],
                f"{COMPOUND}/{phase}: {candidate} support analysis is synchronized", checks)
        require(states[candidate]["status"] == expected_status and
                states[candidate]["action"] == expected_action,
                f"{COMPOUND}/{phase}: {candidate} state follows shared effective policy", checks)
        require(findings[candidate] == expected_status and actions[candidate] == expected_action,
                f"{COMPOUND}/{phase}: {candidate} finding and queue action agree", checks)

    expected_manuscript = "# Current findings\n\n" + "\n".join(
        f"- {name}: {states[name]['status']}; {states[name]['action']}"
        for name in sorted(states)
    ) + "\n"
    require((root / "manuscript/results.md").read_text(encoding="utf-8") == expected_manuscript,
            f"{COMPOUND}/{phase}: compound manuscript is synchronized", checks)


def validate_fields(case_root: Path, case_id: str, fields: list[dict],
                    checks: list[str]) -> tuple[int, int]:
    require(len({field["id"] for field in fields}) == len(fields),
            f"{case_id}: field IDs are unique", checks)
    for field in fields:
        for phase in ("pre", "post"):
            require(observed_value(case_root / TREE[phase], field) == field[phase],
                    f"{case_id}: {field['id']} {phase} value matches fixture", checks)
        expected_operation = "change" if field["pre"] != field["post"] else "preserve"
        require(field["operation"] == expected_operation,
                f"{case_id}: {field['id']} operation follows from its two values", checks)
    stale_failures = sum(observed_value(case_root / "workspace", field) != field["post"]
                         for field in fields)
    post_passes = sum(observed_value(case_root / "gold", field) == field["post"] for field in fields)
    require(stale_failures > 0, f"{case_id}: starting workspace fails reference checks", checks)
    require(post_passes == len(fields), f"{case_id}: reference passes every check", checks)
    return stale_failures, len(fields)


def file_set(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=Path, default=REPO / "tasks" / "rna_mixed")
    parser.add_argument("--selection", type=Path,
                        default=REPO / "data" / "bixbench" / "rna_mixed_selection.json")
    args = parser.parse_args()
    checks: list[str] = []
    selection = read_json(args.selection)
    require(selection["validation"] == "PASS", "capsule selection is marked PASS", checks)
    require(selection["capsule_files"] == {"genes": 63677, "samples": 30, "conditions": 10},
            "capsule selection has 63,677 genes, 30 samples, and 10 conditions", checks)
    require(sorted(p.name for p in args.tasks.iterdir() if p.is_dir()) == [*STANDALONES, COMPOUND],
            "six case folders m-01 .. m-06", checks)

    summaries = {}
    for case_id in STANDALONES:
        case_root = args.tasks / case_id
        task = read_json(case_root / "task.json")
        fields = task["fields"]
        roles = Counter(field["role"] for field in fields)
        require(dict(roles) == EXPECTED_ROLES,
                f"{case_id}: layer census is direct=1, C1=3, C2=3, C3=2, protected=3", checks)
        require(all(field["operation"] == "preserve" for field in fields
                    if field["role"] == "protected"), f"{case_id}: all protected fields preserve", checks)
        c3_ops = [field["operation"] for field in fields if field["role"] == "C3"]
        require(c3_ops == EXPECTED_C3_OPERATIONS[case_id],
                f"{case_id}: C3 operations match the case design", checks)
        require(file_set(case_root / "workspace") == file_set(case_root / "gold"),
                f"{case_id}: workspace and gold file topology matches", checks)
        if case_id == "m-01":
            for relative in CAPSULE_INPUTS:
                require(digest(case_root / "workspace" / relative) == digest(case_root / "gold" / relative),
                        f"{case_id}: executable capsule input {relative} is preserved", checks)
        prompt = task["turns"][0]
        require(not any(fragment in prompt for fragment in FORBIDDEN_PROMPT_PATHS),
                f"{case_id}: prompt does not name downstream files", checks)
        for phase in ("pre", "post"):
            validate_standalone_semantics(case_root, case_id, phase, selection, checks)
        stale_failures, field_count = validate_fields(case_root, case_id, fields, checks)
        summaries[case_id] = {"fields": field_count, "stale_failures": stale_failures}

    compound = args.tasks / COMPOUND
    task = read_json(compound / "task.json")
    compound_prompt = task["turns"][0]
    for required_text in (
        "Sample 6-3 is corrected from Cisplatin_IC50 to",
        "Evidence E1 is withdrawn after quality-control failure",
        "Evidence E2 remains current",
        "raises minimum_supports from 2 to 3",
        "dated decisions under P0 do not change",
    ):
        require(required_text in compound_prompt,
                f"{COMPOUND}: prompt states authoritative transition: {required_text}", checks)
    require(not any(fragment in compound_prompt for fragment in FORBIDDEN_PROMPT_PATHS),
            f"{COMPOUND}: prompt does not name downstream files", checks)
    compound_roles = Counter(field["role"] for field in task["fields"])
    require(dict(compound_roles) == {"direct": 3, "C1": 5, "C2": 3, "C3": 6, "protected": 3},
            f"{COMPOUND}: field-level compound layer census is fixed", checks)
    for relative in CAPSULE_INPUTS:
        require(digest(compound / "workspace" / relative) == digest(compound / "gold" / relative),
                f"{COMPOUND}: executable capsule input {relative} is preserved", checks)
    for phase in ("pre", "post"):
        validate_compound_semantics(compound, phase, checks)
    stale_failures, field_count = validate_fields(compound, COMPOUND, task["fields"], checks)
    summaries[COMPOUND] = {"fields": field_count, "stale_failures": stale_failures}

    print(json.dumps({"checks_passed": len(checks), "cases": summaries}, indent=1))


if __name__ == "__main__":
    main()
