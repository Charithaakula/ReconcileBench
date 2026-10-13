#!/usr/bin/env python3
"""Score the 20 VisText-General evidence-correction episodes (Table 3, 'VisText-General /
Evidence').

Each evidence episode is a full VisText source correction plus the three typed records. This
scorer grades the 12 retained site types in the final workspace, asks the prose judge about the
six prose types where the correction changes them, and adds the two typed booleans and the
held-fixed threshold from score_general_records.py. Every outcome comes from the same final
workspace, so episode closure is a property of one agent run.

    python scorers/score_general_evidence.py --model <model> --runs runs/general_propagation --out <out.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "reconcilebench"))

import claim_rules as CR  # noqa: E402
import grade_vis_atlas as GR  # noqa: E402
import judge_claim as J  # noqa: E402
from judge_compare import judge_one  # noqa: E402

import score_general_records as R  # noqa: E402


CORE = (
    "textsem_superlative",
    "list_ranking",
    "json_leader",
    "json_mean",
    "textval_chart_top3",
    "textval_cross_rank",
    "textval_atlas_dashboard",
    "textval_atlas_overview",
    "exec_test",
    "control_revision_log",
    "viz_vector",
    "textval_atlas_concentration",
)
PROSE = {
    "textsem_superlative",
    "textval_chart_top3",
    "textval_cross_rank",
    "textval_atlas_dashboard",
    "textval_atlas_overview",
    "textval_atlas_concentration",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--model-dir", default=None,
                    help="episode folder suffix, e.g. claude-opus-5 (default: --model)")
    ap.add_argument("--runs", required=True, type=Path, help="suite runs root holding shard subfolders")
    ap.add_argument("--allow-missing", action="store_true", help="score only the episodes present")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.model_dir = args.model_dir or args.model

    jobs, base_rows = [], []
    cache_dir = args.out.parent / f"judge_cache_evidence_{args.model}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_lock = threading.Lock()
    run_root = args.runs
    for seed in range(1, 21):
        base_id = f"atlas-{seed:02d}"
        task_id = f"evidence-{base_id}"
        exp = GR._resolve(json.loads((REPO / "tasks" / "general" / base_id / "task.json").read_text())["exp"])
        hits = sorted(run_root.glob(f"*/{task_id}_{args.model_dir}"))
        run_dir = hits[0] if hits else run_root / f"{task_id}_{args.model_dir}"
        if not run_dir.is_dir():
            if args.allow_missing:
                continue
            raise SystemExit(f"missing run directory: {run_dir}")
        grade = GR.grade(str(run_dir), exp, only=set(CORE))
        ordinary = {site: grade["outcomes"].get(site) == "ok" for site in CORE}
        row = {
            "workspace": base_id,
            "task_id": task_id,
            "run_dir": run_dir,
            "exp": exp,
            "ordinary": ordinary,
            "affected_sites": [site for site in CORE if site in set(exp["broken"])],
            "preservation_sites": [site for site in CORE if site not in set(exp["broken"])],
            "deterministic_grade": grade,
        }
        base_rows.append(row)
        # The semantic judge evaluates affected prose propositions. A prose site the event does
        # not change has no post-event target proposition; it must be preserved exactly, which the
        # deterministic no-change grader already checks.
        for site in sorted(PROSE & set(row["affected_sites"])):
            rel = GR.rel_for(site, exp["code"], exp["target"])
            jobs.append({
                "row": row,
                "site": site,
                "rel": rel,
                "candidate": GR._read(str(run_dir), rel),
                "grader": grade["outcomes"].get(site),
            })

    def judge(job: dict) -> dict:
        # Key the cache on the judged text too, so a re-run episode is never
        # scored with a verdict cached for different workspace text.
        cand_sha = hashlib.sha256((job['candidate'] or '').encode()).hexdigest()[:16]
        cache_path = cache_dir / f"{job['row']['workspace']}__{job['site']}__{cand_sha}.json"
        if cache_path.is_file():
            cached = json.loads(cache_path.read_text())
            if cached.get("judge") is not None:
                return cached
        all_votes = []
        for attempt in range(1, 4):
            verdict, outcome, votes, prompt = judge_one(
                job["site"], job["row"]["exp"], job["candidate"], job["grader"]
            )
            all_votes.extend(votes)
            if verdict is not None:
                break
        rule = CR.RULES[job["site"]]
        result = {
            "workspace": job["row"]["workspace"],
            "task_id": job["row"]["task_id"],
            "site": job["site"],
            "rel": job["rel"],
            "grader": job["grader"],
            "judge": verdict,
            "outcome": outcome,
            "votes": all_votes,
            "attempts": attempt,
            "prompt": prompt,
            "rule": {
                "defn": rule["defn"], "quantity": rule["quantity"],
                "prose": rule["prose"], "expr": rule["expr"],
                "fixed": rule.get("fixed"),
                "presence": CR.PRESENCE.get(job["site"], "required"),
            },
            "want": CR.want_text(job["site"], job["row"]["exp"]),
        }
        if verdict is not None:
            with cache_lock:
                cache_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        judged = list(pool.map(judge, jobs))
    undecided = [row for row in judged if row["judge"] is None]
    if undecided:
        undecided_path = args.out.parent / f"undecided_evidence_{args.model}.json"
        undecided_path.write_text(json.dumps(undecided, indent=2, sort_keys=True) + "\n")
        raise SystemExit(
            f"{len(undecided)} prose judgment(s) undecided; details: {undecided_path}"
        )
    by_key = {(row["workspace"], row["site"]): row["judge"] for row in judged}

    episodes = []
    by_site = {site: {"affected_correct": 0, "affected_total": 0,
                      "preservation_correct": 0, "preservation_total": 0}
               for site in CORE}
    for row in base_rows:
        for site in PROSE & set(row["affected_sites"]):
            row["ordinary"][site] = bool(by_key[(row["workspace"], site)])
        ordinary_a = sum(row["ordinary"][site] for site in row["affected_sites"])
        ordinary_b = sum(row["ordinary"][site] for site in row["preservation_sites"])
        for site in row["affected_sites"]:
            by_site[site]["affected_total"] += 1
            by_site[site]["affected_correct"] += int(row["ordinary"][site])
        for site in row["preservation_sites"]:
            by_site[site]["preservation_total"] += 1
            by_site[site]["preservation_correct"] += int(row["ordinary"][site])

        typed = R.grade_episode(R.TASKS / row["task_id"], row["run_dir"], args.model)
        # The source correction is judged on the parsed CSV (label -> value), as the grader
        # judges it. score_general_records.py also reports a stricter text-hash check, but a
        # reordered row or a changed line ending is not a failed correction.
        authority_ok = bool(row["deterministic_grade"]["source_edit_ok"])
        affected_correct = ordinary_a + typed["affected_correct"]
        affected_total = len(row["affected_sites"]) + typed["affected_total"]
        preservation_correct = ordinary_b + int(typed["preservation_ok"])
        preservation_total = len(row["preservation_sites"]) + 1
        closed = (
            affected_correct == affected_total
            and preservation_correct == preservation_total
            and authority_ok
        )
        episodes.append({
            "workspace": row["workspace"],
            "task_id": row["task_id"],
            "ordinary_affected_correct": ordinary_a,
            "ordinary_affected_total": len(row["affected_sites"]),
            "ordinary_preservation_correct": ordinary_b,
            "ordinary_preservation_total": len(row["preservation_sites"]),
            "typed_affected_correct": typed["affected_correct"],
            "typed_affected_total": typed["affected_total"],
            "typed_preservation_ok": typed["preservation_ok"],
            "typed_truth_ok": typed["truth_ok"],
            "typed_decision_ok": typed["decision_ok"],
            "authority_ok": authority_ok,
            "typed_serialization_authority_ok": typed["authority_ok"],
            "affected_correct": affected_correct,
            "affected_total": affected_total,
            "preservation_correct": preservation_correct,
            "preservation_total": preservation_total,
            "closed": closed,
            "ordinary_outcomes": row["ordinary"],
            "routine_correct": ordinary_a - int(
                "viz_vector" in row["affected_sites"] and row["ordinary"]["viz_vector"]
            ),
            "routine_total": len(row["affected_sites"]) - int(
                "viz_vector" in row["affected_sites"]
            ),
            "visual_correct": int(
                "viz_vector" in row["affected_sites"] and row["ordinary"]["viz_vector"]
            ),
            "visual_total": int("viz_vector" in row["affected_sites"]),
        })

    summary = {
        "workspaces": len(episodes),
        "affected_correct": sum(row["affected_correct"] for row in episodes),
        "affected_total": sum(row["affected_total"] for row in episodes),
        "preservation_correct": sum(row["preservation_correct"] for row in episodes),
        "preservation_total": sum(row["preservation_total"] for row in episodes),
        "authority_correct": sum(row["authority_ok"] for row in episodes),
        "closed": sum(row["closed"] for row in episodes),
        "ordinary_affected_correct": sum(row["ordinary_affected_correct"] for row in episodes),
        "ordinary_affected_total": sum(row["ordinary_affected_total"] for row in episodes),
        "typed_affected_correct": sum(row["typed_affected_correct"] for row in episodes),
        "typed_affected_total": sum(row["typed_affected_total"] for row in episodes),
        "typed_truth_correct": sum(row["typed_truth_ok"] for row in episodes),
        "typed_truth_total": len(episodes),
        "typed_decision_correct": sum(row["typed_decision_ok"] for row in episodes),
        "typed_decision_total": len(episodes),
        "routine_correct": sum(row["routine_correct"] for row in episodes),
        "routine_total": sum(row["routine_total"] for row in episodes),
        "visual_correct": sum(row["visual_correct"] for row in episodes),
        "visual_total": sum(row["visual_total"] for row in episodes),
    }
    payload = {
        "model": args.model, "summary": summary,
        "by_site": by_site, "episodes": episodes,
        "judge_provenance": J.provenance(),
        "judge_rows": judged,
        "grader_sha256": sha(REPO / "reconcilebench" / "grade_vis_atlas.py"),
        "scorer_sha256": sha(Path(__file__)),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
