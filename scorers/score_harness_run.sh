#!/bin/bash
# Score every suite of a Codex CLI or Claude Code run with the same scorers as the mini-SWE-agent
# runs. These harnesses record no end-of-episode grade, so RNA mixed and prose evidence are graded
# from the final workspaces first (score_rna_mixed.py --runs, grade_offline_atlas.py).
# Interpreter and keys as in score_mini_run.sh.
#
#   scorers/score_harness_run.sh <label> <workspace-suffix>
#   scorers/score_harness_run.sh codex-gpt-5.6-sol gpt-5.6-sol
#   scorers/score_harness_run.sh claude-code-opus-5 claude-opus-5-cc
set -euo pipefail
D="$(cd "$(dirname "$0")/.." && pwd)"; L=$1; S=$2
G=${GRADE_PYTHON:-${PYTHON:-python3}}; T=${TMPDIR:-/tmp}
if [[ -f "$D/.env" ]]; then set -a; . "$D/.env"; set +a; fi
O="$D/results"; C="$D/scorers"
mkdir -p "$O"/{general_propagation,health,rna_labels,rna_mixed,prose_evidence,prose_criterion,retraction,noop}
echo "== VisText-General"
$G -B "$C/score_general_records.py" --model "$L" --model-dir "$S" --runs "$D/runs/general_propagation" --out "$O/general_propagation/records_$L.json" > /dev/null
$G -B "$C/score_general_evidence.py" --model "$L" --model-dir "$S" --runs "$D/runs/general_propagation" --workers 8 --out "$O/general_propagation/evidence_$L.json" | grep -E '"closed"'
$G "$C/table3_general.py" "$O/general_propagation/evidence_$L.json" "$O/general_propagation/records_$L.json" "$O" "$L"
echo "== VisText-Health"
(cd "$T" && $G -B "$C/score_health.py" "$D/runs/health/${L}_*" "$S" "$O/health/scored_$L.json" "$L" | tail -1)
echo "== BixBench-RNA condition labels"
(cd "$T" && $G -B "$C/score_rna_labels.py" "$D/runs/rna_labels/${L}_*" "$O/rna_labels/scored_$L.json")
echo "== BixBench-RNA mixed"
$G -B "$C/score_rna_mixed.py" --runs "$D/runs/rna_mixed/${L}_*" --out "$O/rna_mixed/res_${L}_graded.jsonl" | tail -6
$G "$C/table3_rna_mixed.py" "$O/rna_mixed/scored_$L.json" "$O/rna_mixed/res_${L}_graded.jsonl"
echo "== Prose evidence (judge, offline grade, criterion-claim + review-flag conjunction)"
(cd "$D" && $G -B reconcilebench/judge_compare.py --runs "$D/runs/prose_evidence/${L}_*" --base-only --workers 8 --out "$O/prose_evidence/judge_$L.json" | tail -1)
$G -B "$C/grade_offline_atlas.py" "$O/prose_evidence/res_${L}_0.jsonl" "$D/tasks/general" "$O/prose_evidence/res_${L}_graded.jsonl"
$G -B "$C/score_prose_evidence.py" "$O/prose_evidence/judge_$L.json" "$O/prose_evidence/res_${L}_graded.jsonl" "$O/prose_evidence/scored_$L.json" | tail -1
echo "== Prose criterion"
(cd "$T" && $G -B "$C/score_prose_criterion.py" "$D/runs/prose_criterion/${L}_*" "$O/prose_criterion/scored_$L.json" | grep -E '"closed"|statements_correct')
echo "== Already applied and retraction"
(cd "$T" && $G -B "$C/score_noop.py" "$D/runs/noop/${L}_*" "$O/noop/scored_$L.json" | grep -E 'abstained|changed')
(cd "$T" && $G -B "$C/score_retraction.py" "$D/runs/retraction/${L}_*" "$O/retraction/scored_$L.json" | grep -E 'restored|third_state|collateral|closed')
echo "SCORED $L"
