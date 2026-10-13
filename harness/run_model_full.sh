#!/bin/bash
# The full protocol for one model in mini-SWE-agent: the 106 main episodes, 20 already-applied
# (no-op) episodes and 60 retraction episodes. Retraction episodes use <model>-retraction.yaml,
# which raises the episode step budget to 400.
#
#   harness/run_model_full.sh <model> [--no-retraction]
#   harness/run_model_full.sh gpt-5.6-sol
#   harness/run_model_full.sh claude-opus-5
#
# Suites run in parallel; each writes its own logs and results.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"; M=$1; R=$REPO/harness; I=$R/ids; mkdir -p "$REPO/logs"
run() { $R/run_suite.sh $1 $2 @$I/$1.txt $3 > $REPO/logs/driver_$1_$2.log 2>&1 & }
run general_propagation $M 4
run health              $M 3
run rna_labels          $M 2
run rna_mixed           $M 2
run prose_evidence      $M 3
run prose_criterion     $M 3
run noop                $M 3
if [ "${2:-}" != "--no-retraction" ]; then
  run retraction        $M-retraction 4
fi
wait
echo "${M}_FULL_EXIT $(date)"
