#!/usr/bin/env python3
"""Audit the VisText-General propagation fixtures (tasks/general_propagation). Fails closed.

    python generators/check_general_propagation.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


TASKS = Path(__file__).resolve().parents[1] / "tasks" / "general_propagation"


def main() -> None:
    ids = sorted(p.name for p in TASKS.iterdir() if p.is_dir())
    assert ids == sorted(f"{t}-atlas-{s:02d}" for s in range(1, 21) for t in ("evidence", "policy"))
    for task_id in ids:
        task_dir = TASKS / task_id
        task = json.loads((task_dir / "task.json").read_text())
        meta, ws = task["typed"], task_dir / "workspace"
        assert meta["transition"] == task_id.split("-")[0]
        policy = json.loads((ws / "policy/review-policy.json").read_text())
        truth = json.loads((ws / "analysis/criterion-status.json").read_text())
        decision = json.loads((ws / "decisions/review-queue.json").read_text())
        pre = meta["pre_ratio"] >= meta["old_threshold"]
        post = meta["post_ratio"] >= meta["new_threshold"]
        assert pre != post, task_id
        assert truth["criterion_satisfied"] is pre
        assert decision["review_required"] is pre
        assert policy["minimum_leader_to_median_multiple"] == meta["old_threshold"]
        assert truth["observed_leader_to_median_multiple"] == meta["pre_ratio"]
        assert len(meta["affected_fields"]) == 2
        assert meta["expected_criterion_satisfied"] is post
        assert meta["expected_review_required"] is post
        assert len(task["turns"]) == 4
        source = hashlib.sha256((ws / meta["source_rel"]).read_text().encode()).hexdigest()
        if meta["transition"] == "evidence":
            assert meta["old_threshold"] == meta["new_threshold"]
            assert source != meta["source_post_sha256"]
        else:
            assert meta["pre_ratio"] == meta["post_ratio"]
            assert meta["old_threshold"] != meta["new_threshold"]
            assert source == meta["source_post_sha256"]
    print(f"PASS: {len(ids)} fixtures audited")


if __name__ == "__main__":
    main()
