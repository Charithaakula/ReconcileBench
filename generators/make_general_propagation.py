#!/usr/bin/env python3
"""Build the VisText-General propagation episodes: tasks/general_propagation.

Each of the 20 VisText-General workspaces (tasks/general/atlas-NN) yields two episodes. Both add
three small typed records whose semantics can be graded without an LLM judge:

    policy/review-policy.json        authoritative review threshold
    analysis/criterion-status.json   criterion truth, derived from the target chart and the policy
    decisions/review-queue.json      review decision, derived from the criterion truth

    evidence-atlas-NN   the base episode's source correction; the policy is held fixed
    policy-atlas-NN     the review threshold is revised; the chart data are held fixed

In both, criterion_satisfied and review_required must flip, and the held-fixed value (the
threshold, or the observed ratio) must not move.

    python generators/make_general_propagation.py
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import shutil
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "tasks" / "general"
OUT = REPO / "tasks" / "general_propagation"


def _ratio(csv_text: str) -> float:
    values = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        for key in ("value", "v", "amount"):
            if key in row:
                try:
                    values.append(float(row[key]))
                except (TypeError, ValueError):
                    pass
                break
    values.sort(reverse=True)
    return values[0] / values[len(values) // 2]


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _threshold_between(a: float, b: float) -> float:
    # Six significant decimals are enough to stay strictly between every observed pair.
    value = round((a + b) / 2.0, 6)
    if not min(a, b) < value < max(a, b):
        value = (a + b) / 2.0
    return value


def _state_documents(criterion_id: str, ratio: float, threshold: float) -> tuple[dict, dict, dict]:
    holds = ratio >= threshold
    policy = {
        "record_type": "authoritative_decision_criterion",
        "criterion_id": criterion_id,
        "minimum_leader_to_median_multiple": threshold,
    }
    truth = {
        "record_type": "derived_criterion_truth",
        "criterion_id": criterion_id,
        "depends_on": ["target_chart_values", "review-policy.json"],
        "observed_leader_to_median_multiple": round(ratio, 6),
        "criterion_satisfied": holds,
    }
    decision = {
        "record_type": "derived_review_decision",
        "decision_id": "review_queue",
        "licensed_by": criterion_id,
        "depends_on": ["criterion-status.json#criterion_satisfied"],
        "review_required": holds,
    }
    return policy, truth, decision


def _task(seed: int, transition: str, metadata: dict, source_turn: str) -> dict:
    task_id = f"{transition}-atlas-{seed:02d}"
    if transition == "evidence":
        turn = source_turn + (
            " Apply this authoritative correction and reconcile every derived record in the "
            "workspace. Policies that were not revised must remain unchanged."
        )
    else:
        turn = (
            "The authoritative review policy has been revised: criterion "
            f"{metadata['criterion_id']} now requires a leader-to-median multiple of "
            f"{metadata['new_threshold']}, replacing {metadata['old_threshold']}. "
            "The underlying chart data have not changed. Reconcile the workspace so every "
            "current derived record and decision is consistent with this revision, while "
            "preserving evidence and history that remain valid."
        )
    warmup = [
        "Read README.md and briefly identify the workspace's sources of record and its "
        "consistency requirement. Do not edit files yet.",
        "Locate the review criterion, its current truth record, and the decision that depends "
        "on it. Briefly report their current values; do not edit files yet.",
        "Before the handoff, confirm which records are authoritative and which are derived. "
        "Do not edit files yet.",
    ]
    return {
        "id": task_id,
        "probe": "TYPED",  # the runner records the episode; scorers/score_general_*.py grade it
        "arm": transition,
        "turns": warmup + [turn],
        "typed": metadata,
    }


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    built = 0

    for seed in range(1, 21):
        source_dir = SOURCE / f"atlas-{seed:02d}"
        source_task = json.loads((source_dir / "task.json").read_text())
        exp = source_task["exp"]
        target = exp["target"]
        rel_source = f"data/{target}/values.csv"
        pre_text = (source_dir / "workspace" / rel_source).read_text()
        post_text = exp["source_post"][rel_source]
        pre_ratio, post_ratio = _ratio(pre_text), _ratio(post_text)
        evidence_threshold = _threshold_between(pre_ratio, post_ratio)
        criterion_id = f"chart-{target}-review"

        # Both episodes start from an explicit, internally consistent state. The evidence
        # episode uses a threshold between the old and new ratio, so the truth flips. The
        # policy episode starts just below the unchanged ratio and moves just above it.
        transition_specs = {
            "evidence": {
                "pre_ratio": pre_ratio,
                "post_ratio": post_ratio,
                "old_threshold": evidence_threshold,
                "new_threshold": evidence_threshold,
                "source_post": post_text,
            },
            "policy": {
                "pre_ratio": pre_ratio,
                "post_ratio": pre_ratio,
                # Integer rules keep the event readable while staying strictly on opposite
                # sides of the unchanged ratio. atlas-01 moves from 6x to 10x.
                "old_threshold": float(max(1, math.floor(pre_ratio) - 1)),
                "new_threshold": float(math.ceil(pre_ratio) + 2),
                "source_post": pre_text,
            },
        }

        for transition, spec in transition_specs.items():
            task_id = f"{transition}-atlas-{seed:02d}"
            task_dir = OUT / task_id
            workspace = task_dir / "workspace"
            shutil.copytree(source_dir / "workspace", workspace)
            policy, truth, decision = _state_documents(
                criterion_id, spec["pre_ratio"], spec["old_threshold"]
            )
            _write_json(workspace / "policy" / "review-policy.json", policy)
            _write_json(workspace / "analysis" / "criterion-status.json", truth)
            _write_json(workspace / "decisions" / "review-queue.json", decision)

            post_holds = spec["post_ratio"] >= spec["new_threshold"]
            pre_holds = spec["pre_ratio"] >= spec["old_threshold"]
            assert pre_holds != post_holds
            metadata = {
                "seed": seed,
                "transition": transition,
                "criterion_id": criterion_id,
                "source_rel": rel_source,
                "source_post_sha256": hashlib.sha256(spec["source_post"].encode()).hexdigest(),
                "old_threshold": spec["old_threshold"],
                "new_threshold": spec["new_threshold"],
                "pre_ratio": round(spec["pre_ratio"], 6),
                "post_ratio": round(spec["post_ratio"], 6),
                "expected_criterion_satisfied": post_holds,
                "expected_review_required": post_holds,
                "affected_fields": [
                    "analysis/criterion-status.json#criterion_satisfied",
                    "decisions/review-queue.json#review_required",
                ],
                "preservation_field": (
                    "policy/review-policy.json#minimum_leader_to_median_multiple"
                    if transition == "evidence" else
                    "analysis/criterion-status.json#observed_leader_to_median_multiple"
                ),
            }
            task = _task(seed, transition, metadata, source_task["turns"][-1])
            (task_dir / "task.json").write_text(json.dumps(task, indent=2) + "\n")
            built += 1
    print(f"Built {built} episodes in {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
