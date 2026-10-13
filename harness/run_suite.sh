#!/bin/bash
# Run one ReconcileBench suite for one model in mini-SWE-agent.
#
#   harness/run_suite.sh <suite> <model> <ids-comma-or-@file> [shards]
#   harness/run_suite.sh health claude-opus-5 @harness/ids/health.txt 3
#
#   suite   one of the folders under tasks/, or prose_evidence (tasks/general),
#           prose_criterion (tasks/general_criterion), noop (tasks/general_noop) or
#           retraction (tasks/general_retraction)
#   model   file stem in harness/models/, e.g. gpt-5.6-sol or claude-opus-5-retraction
#   ids     comma-separated task ids, or @path to a file with one id per line
#   shards  parallel workers (default 4)
#
# GPT model files are merged over harness/config.yaml; the Claude files are complete configs.
# Outputs (git-ignored):
#   results/<suite>/res_<model>_<shard>.jsonl   one record per episode (grade, cost, turns)
#   traces/<suite>/<id>_<model-name>.json       full message trace
#   runs/<suite>/<model>_<shard>/<id>_<model-name>/  final workspace (what the scorers read)
#   logs/<suite>_<model>_<shard>.log            runner output
#
# Environment: PYTHON (default python3) must have the requirements installed.
# OPENAI_API_KEY / ANTHROPIC_API_KEY come from the environment or a git-ignored .env file.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SUITE=$1; CFG=$2; IDS=$3; SHARDS=${4:-4}
case "$SUITE" in
  prose_evidence)  TASKS=$REPO/tasks/general ;;
  prose_criterion) TASKS=$REPO/tasks/general_criterion ;;
  noop)            TASKS=$REPO/tasks/general_noop ;;
  retraction)      TASKS=$REPO/tasks/general_retraction ;;
  *)               TASKS=$REPO/tasks/$SUITE ;;
esac
[[ -d $TASKS ]] || { echo "unknown suite $SUITE" >&2; exit 2; }
PY=${PYTHON:-python3}
MODEL_FILE="$REPO/harness/models/$CFG.yaml"
if grep -q '^environment:' "$MODEL_FILE"; then CFG_ARGS=(--config "$MODEL_FILE")
else CFG_ARGS=(--config "$REPO/harness/config.yaml" --model-yaml "$MODEL_FILE"); fi

all=()   # macOS ships bash 3.2, which has no mapfile
if [[ $IDS == @* ]]; then while IFS= read -r x; do [[ -n $x ]] && all+=("$x"); done < "${IDS#@}"
else IFS=, read -ra all <<< "$IDS"; fi
mkdir -p "$REPO/results/$SUITE" "$REPO/traces/$SUITE" "$REPO/runs/$SUITE" "$REPO/logs"
if [[ -f "$REPO/.env" ]]; then set -a; . "$REPO/.env"; set +a; fi
export MSWEA_SILENT_STARTUP=1 RB_RUNS_ROOT="$REPO/runs/$SUITE"

pids=()
for ((s=0; s<SHARDS; s++)); do
  sel=()
  for ((i=s; i<${#all[@]}; i+=SHARDS)); do sel+=("${all[$i]}"); done
  [[ ${#sel[@]} -eq 0 ]] && continue
  list=$(IFS=,; echo "${sel[*]}")
  (cd "$REPO" && "$PY" harness/run_tasks.py "${CFG_ARGS[@]}" --env "${RB_ENV:-local}" \
      --tasks "$TASKS" --ids "$list" \
      --out "$REPO/results/$SUITE/res_${CFG}_$s.jsonl" \
      --dump_dir "$REPO/traces/$SUITE" \
      --runs_dir "$REPO/runs/$SUITE/${CFG}_$s" \
      > "$REPO/logs/${SUITE}_${CFG}_$s.log" 2>&1) &
  pids+=($!)
done
rc=0; for p in "${pids[@]}"; do wait "$p" || rc=1; done
echo "suite=$SUITE model=$CFG episodes=${#all[@]} shards=$SHARDS exit=$rc"
exit $rc
