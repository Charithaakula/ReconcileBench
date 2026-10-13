#!/usr/bin/env python3
"""Deterministic scorer for the BixBench-RNA mixed evidence/policy cases (tasks/rna_mixed).

Every scored field in a case's task.json names a file, a JSON pointer (or "sha256" for a whole
file) and the reference value. A field is correct when the final workspace holds the reference
value. Fields carry the paper's layers: direct, C1, C2, C3, and protected (dated history and
unaffected controls, which must not change).

    python scorers/score_rna_mixed.py <case-id> <final-workspace> [--output grade.json]
    python scorers/score_rna_mixed.py --runs '<runs-glob, e.g. runs/rna_mixed/codex-gpt-5.6-sol_*>' --out <res.jsonl>

mini-SWE-agent runs are graded in-run by harness/run_tasks.py with grade(); the --runs form
applies the same function to workspaces saved by the Codex CLI and Claude Code harnesses.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
from pathlib import Path


TASKS = Path(__file__).resolve().parents[1] / "tasks" / "rna_mixed"
ROLES = ("direct", "C1", "C2", "C3", "protected")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def pointer(value, selector: str):
    if selector == "/":
        return value
    for token in selector.strip("/").split("/"):
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def observed(root: Path, field: dict):
    path = root / field["file"]
    if not path.is_file():
        return None
    if field["selector"] == "sha256":
        return digest(path)
    try:
        return pointer(read_json(path), field["selector"])
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
        return None


def file_map(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): digest(path)
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def prose_semantics(root: Path, post: Path) -> dict:
    manuscript_path = root / "manuscript/results.md"
    manuscript = manuscript_path.read_text(encoding="utf-8") if manuscript_path.is_file() else ""
    if (post / "findings/current-finding.json").is_file():
        wanted_finding = read_json(post / "findings/current-finding.json")
        wanted_action = read_json(post / "decisions/validation-queue.json")
        required = [
            str(wanted_finding["candidate"]),
            str(wanted_finding["status"]),
            str(wanted_action["operation"]),
        ]
        present = {f"manuscript:{token}": token in manuscript for token in required}
        synchronized = bool(manuscript) and all(present.values())
        files = ["manuscript/results.md"]
    else:
        findings = read_json(post / "findings/current-findings.json")
        actions = read_json(post / "decisions/validation-queue.json")
        handoff_path = root / "project/handoff.md"
        handoff = handoff_path.read_text(encoding="utf-8") if handoff_path.is_file() else ""
        present = {}
        for candidate in sorted(findings):
            present[f"manuscript:{candidate}"] = candidate in manuscript
            present[f"manuscript:{candidate}:{findings[candidate]}"] = (
                findings[candidate] in manuscript
            )
            present[f"manuscript:{candidate}:{actions[candidate]}"] = actions[candidate] in manuscript
            present[f"handoff:{candidate}"] = candidate in handoff
            present[f"handoff:{candidate}:{actions[candidate]}"] = actions[candidate] in handoff
        synchronized = bool(manuscript) and bool(handoff) and all(present.values())
        files = ["manuscript/results.md", "project/handoff.md"]
    return {
        "files": files,
        "required_tokens": present,
        "synchronized": synchronized,
    }


def grade(case_id: str, root: Path) -> dict:
    fixture = TASKS / case_id
    pre = fixture / "workspace"
    post = fixture / "gold"
    task = read_json(fixture / "task.json")
    outcomes = []
    for field in task["fields"]:
        value = observed(root, field)
        outcomes.append({
            "id": field["id"],
            "role": field["role"],
            "operation": field["operation"],
            "file": field["file"],
            "selector": field["selector"],
            "expected": field["post"],
            "observed": value,
            "correct": value == field["post"],
        })

    roles = {}
    for role in ROLES:
        rows = [row for row in outcomes if row["role"] == role]
        roles[role] = {
            "correct": sum(row["correct"] for row in rows),
            "total": len(rows),
            "complete": bool(rows) and all(row["correct"] for row in rows),
            "failed": [row["id"] for row in rows if not row["correct"]],
        }

    pre_files = file_map(pre)
    post_files = file_map(post)
    actual_files = file_map(root)
    expected_paths = set(pre_files) | set(post_files)
    created = sorted(set(actual_files) - expected_paths)
    deleted = sorted(set(pre_files) - set(actual_files))
    invariant_paths = sorted(
        rel for rel in set(pre_files) & set(post_files) if pre_files[rel] == post_files[rel]
    )
    collateral = sorted(
        rel for rel in invariant_paths if actual_files.get(rel) != pre_files[rel]
    )
    changed_paths = sorted(
        rel for rel in set(pre_files) & set(post_files) if pre_files[rel] != post_files[rel]
    )
    exact_post = sum(actual_files.get(rel) == post_files.get(rel) for rel in post_files)
    prose = prose_semantics(root, post)
    field_closure = all(row["correct"] for row in outcomes)
    strict_closure = (
        field_closure and prose["synchronized"] and not collateral and not created and not deleted
    )
    changed = [row for row in outcomes if row["operation"] == "change"]
    preserved = [row for row in outcomes if row["operation"] == "preserve"]
    structured = [row for row in outcomes if row["selector"] != "sha256"]
    return {
        "case_id": case_id,
        "field_outcomes": outcomes,
        "roles": roles,
        "changed_fields": {
            "correct": sum(row["correct"] for row in changed), "total": len(changed)
        },
        "preserved_fields": {
            "correct": sum(row["correct"] for row in preserved), "total": len(preserved)
        },
        "exact_structured_state": all(row["correct"] for row in structured),
        "prose": prose,
        "files": {
            "expected": len(post_files),
            "exact_post": exact_post,
            "expected_changed": changed_paths,
            "invariant": invariant_paths,
            "collateral_edits": collateral,
            "created": created,
            "deleted": deleted,
        },
        "field_closure": field_closure,
        "strict_closure": strict_closure,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", nargs="?")
    parser.add_argument("workspace", nargs="?", type=Path)
    parser.add_argument("--output", type=Path, help="write one case's grade here")
    parser.add_argument("--runs", help="glob of run folders holding <case-id>_<model> workspaces")
    parser.add_argument("--out", type=Path, help="with --runs: records file, one line per case")
    args = parser.parse_args()
    if args.runs:
        if not args.out:
            parser.error("--runs needs --out")
        with args.out.open("w", encoding="utf-8") as fh:
            for ws in sorted(glob.glob(os.path.join(args.runs, "m-0*_*"))):
                case = os.path.basename(ws).rsplit("_", 1)[0]
                result = grade(case, Path(ws))
                fh.write(json.dumps({"task_id": case, "workspace": os.path.basename(ws),
                                     "grade": result}) + "\n")
                print(case, "strict_closure=%s" % result["strict_closure"])
        return
    if not (args.case_id and args.workspace):
        parser.error("give <case-id> <workspace>, or --runs and --out")
    rendered = json.dumps(grade(args.case_id, args.workspace), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
