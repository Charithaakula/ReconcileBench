#!/bin/bash
# The full protocol for GPT-5.6-SOL (low reasoning) in Codex CLI, one container per episode.
#   harness/codex/run_full.sh [label]
# Needs the episode image (docker build -t reconcilebench-codex:0.157.1 harness/codex) and a
# Codex login at harness/codex/auth/auth.json (git-ignored). Runs sequentially and stops if a
# run_codex.py call exits non-zero (for example when the Codex plan limit is reached).
set -u
REPO="$(cd "$(dirname "$0")/../.." && pwd)"; I=$REPO/harness/ids; T=$REPO/tasks; L=${1:-codex-gpt-5.6-sol}
cd "$REPO/harness/codex"
run() { python3 run_codex.py --suite "$1" --tasks-dir "$2" --ids @$I/$1.txt --label "$L"; }
run general_propagation $T/general_propagation \
 && run health          $T/health \
 && run rna_labels      $T/rna_labels \
 && run rna_mixed       $T/rna_mixed \
 && run prose_evidence  $T/general \
 && run prose_criterion $T/general_criterion \
 && run noop            $T/general_noop \
 && run retraction      $T/general_retraction
echo "CODEX_FULL_EXIT $? $(date)"
