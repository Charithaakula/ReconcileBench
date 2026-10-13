#!/bin/bash
# Score every suite of one mini-SWE-agent model run (harness/run_model_full.sh).
#
#   scorers/score_mini_run.sh <model>
#   scorers/score_mini_run.sh gpt-5.6-sol
#   scorers/score_mini_run.sh claude-opus-5
#
# GRADE_PYTHON (default: $PYTHON, then python3) runs every scorer. On macOS the deterministic
# grader executes model-written tests and SVG under sandbox-exec, which denies the home folder,
# so that interpreter must live outside $HOME (docs/running.md, "Grading"). Prose sites call the
# GPT-5.6-SOL judge, which needs OPENAI_API_KEY.
set -euo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"; M=$1
G=${GRADE_PYTHON:-${PYTHON:-python3}}; T=${TMPDIR:-/tmp}
if [[ -f "$R/.env" ]]; then set -a; . "$R/.env"; set +a; fi
S="$R/scorers"; O="$R/results"
mkdir -p "$O"/{general_propagation,health,rna_labels,rna_mixed,prose_evidence,prose_criterion,retraction,noop}

echo "== VisText-General evidence and rule"
$G -B "$S/score_general_records.py" --model "$M" --runs "$R/runs/general_propagation" \
    --out "$O/general_propagation/records_$M.json" > /dev/null
$G -B "$S/score_general_evidence.py" --model "$M" --runs "$R/runs/general_propagation" \
    --workers 8 --out "$O/general_propagation/evidence_$M.json" | grep -E '"closed"'
$G "$S/table3_general.py" "$O/general_propagation/evidence_$M.json" "$O/general_propagation/records_$M.json" "$O" "$M"

echo "== VisText-Health"
(cd "$T" && $G -B "$S/score_health.py" "$R/runs/health/${M}_*" "$M" "$O/health/scored_$M.json" "$M" | tail -1)

echo "== BixBench-RNA condition labels"
(cd "$T" && $G -B "$S/score_rna_labels.py" "$R/runs/rna_labels/${M}_*" "$O/rna_labels/scored_$M.json")

echo "== BixBench-RNA mixed (graded in-run)"
$G "$S/table3_rna_mixed.py" "$O/rna_mixed/scored_$M.json" "$O"/rna_mixed/res_${M}_*.jsonl

echo "== Prose evidence (judge, then criterion-claim + review-flag conjunction)"
(cd "$R" && $G -B reconcilebench/judge_compare.py \
    --runs "$R/runs/prose_evidence/${M}_*" --base-only --workers 8 \
    --out "$O/prose_evidence/judge_$M.json" | tail -1)
$G -B "$S/score_prose_evidence.py" "$O/prose_evidence/judge_$M.json" \
    "$O/prose_evidence/res_${M}_*.jsonl" "$O/prose_evidence/scored_$M.json"

echo "== Prose criterion revision"
(cd "$T" && $G -B "$S/score_prose_criterion.py" "$R/runs/prose_criterion/${M}_*" \
    "$O/prose_criterion/scored_$M.json" | grep -E '"closed"|statements_correct')

echo "== Already applied (no-op) and retraction"
(cd "$T" && $G -B "$S/score_noop.py" "$R/runs/noop/${M}_*" "$O/noop/scored_$M.json" | grep -E 'abstained|changed')
(cd "$T" && $G -B "$S/score_retraction.py" "$R/runs/retraction/${M}-retraction_*" "$O/retraction/scored_$M.json" | head -9)
echo "SCORED $M"
