#!/usr/bin/env python3
"""Exact scores of the typed records in the VisText-General propagation episodes.

For every episode in tasks/general_propagation: are criterion_satisfied and review_required the
values the transition implies, did the held-fixed value stay fixed (the threshold in evidence
episodes, the observed ratio in rule episodes), and was the authoritative change applied (the
corrected source CSV, or the revised threshold)? Rule episodes are scored entirely here; evidence
episodes combine these fields with the rest of the workspace in score_general_evidence.py.

    python scorers/score_general_records.py --model <model> --runs runs/general_propagation --out <out.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
TASKS = REPO / "tasks" / "general_propagation"


def task_ids() -> list[str]:
    return [f"{t}-atlas-{seed:02d}" for seed in range(1, 21) for t in ("evidence", "policy")]


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _get(doc: dict | None, key: str):
    return doc.get(key) if doc else None


def grade_episode(task_dir: Path, run_dir: Path, model: str) -> dict:
    task = json.loads((task_dir / "task.json").read_text())
    meta = task["typed"]
    transition = meta["transition"]
    truth = _load(run_dir / "analysis" / "criterion-status.json")
    decision = _load(run_dir / "decisions" / "review-queue.json")
    policy = _load(run_dir / "policy" / "review-policy.json")
    truth_ok = _get(truth, "criterion_satisfied") is meta["expected_criterion_satisfied"]
    decision_ok = _get(decision, "review_required") is meta["expected_review_required"]
    if transition == "evidence":
        preserve_ok = _get(policy, "minimum_leader_to_median_multiple") == meta["old_threshold"]
        source = run_dir / meta["source_rel"]
        # Text mode, so CRLF and LF serializations of the same CSV compare equal.
        authority_ok = source.exists() and hashlib.sha256(source.read_text().encode()).hexdigest() == meta[
            "source_post_sha256"
        ]
    else:
        preserve_ok = _get(truth, "observed_leader_to_median_multiple") == meta["pre_ratio"]
        authority_ok = _get(policy, "minimum_leader_to_median_multiple") == meta["new_threshold"]
    return {
        "task_id": task["id"], "model": model,
        "transition": transition, "seed": meta["seed"],
        "truth_ok": truth_ok, "decision_ok": decision_ok,
        "affected_correct": int(truth_ok) + int(decision_ok), "affected_total": 2,
        "preservation_ok": preserve_ok, "authority_ok": authority_ok,
        "core_closed": truth_ok and decision_ok and preserve_ok,
        "closed": truth_ok and decision_ok and preserve_ok and authority_ok,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="run label, e.g. gpt-5.6-sol")
    ap.add_argument("--model-dir", default=None,
                    help="episode folder suffix, e.g. claude-opus-5 (default: --model)")
    ap.add_argument("--runs", required=True, type=Path, help="suite runs root holding shard folders")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    suffix = args.model_dir or args.model
    rows = []
    for task_id in task_ids():
        hits = sorted(args.runs.glob(f"*/{task_id}_{suffix}")) or [args.runs / f"{task_id}_{suffix}"]
        rows.append(grade_episode(TASKS / task_id, hits[0], args.model))
    summary = defaultdict(lambda: {"episodes": 0, "affected_correct": 0,
                                   "affected_total": 0, "preservation_correct": 0,
                                   "authority_correct": 0, "core_closed": 0, "closed": 0})
    for row in rows:
        for key in (row["transition"], "all"):
            s = summary[key]
            s["episodes"] += 1
            s["affected_correct"] += row["affected_correct"]
            s["affected_total"] += row["affected_total"]
            s["preservation_correct"] += int(row["preservation_ok"])
            s["authority_correct"] += int(row["authority_ok"])
            s["core_closed"] += int(row["core_closed"])
            s["closed"] += int(row["closed"])
    payload = {"model": args.model, "summary": dict(summary), "episodes": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
