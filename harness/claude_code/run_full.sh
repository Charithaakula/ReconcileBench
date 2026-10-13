#!/bin/bash
# The full protocol for Claude Opus 5 (low effort) in Claude Code: 186 episodes in three parallel
# lanes, one container per episode, network off.
#   harness/claude_code/run_full.sh [label] [model]
# Build the images first:
#   docker build -t reconcilebench-claude-code:2.1.289 harness/claude_code
#   docker build -t reconcilebench-claude-code:2.1.289-mpl3.9.4 -f harness/claude_code/Dockerfile.mpl harness/claude_code
# The mpl image adds matplotlib 3.9.4, Pillow 11.3.0 and zlib-ng 2.2.4, so re-rendered charts are
# byte-identical to the shipped ones. ANTHROPIC_API_KEY must be set.
set -u
REPO="$(cd "$(dirname "$0")/../.." && pwd)"; I=$REPO/harness/ids; T=$REPO/tasks
L=${1:-claude-code-opus-5}; M=${2:-claude-opus-5}; IMG=reconcilebench-claude-code:2.1.289-mpl3.9.4
cd "$REPO/harness/claude_code"; mkdir -p "$REPO/logs"
pick() { awk -v i=$1 'NF && (NR-1)%3==i' $2 | paste -sd, -; }
lane() {
  local i=$1
  run() {
    local ids; ids=$(pick $i $I/$1.txt)
    [ -n "$ids" ] && python3 run_claude_code.py --suite $1 --tasks-dir $2 --ids "$ids" --label $L --model $M --image $IMG
  }
  run general_propagation $T/general_propagation
  run health              $T/health
  run noop                $T/general_noop
  run prose_evidence      $T/general
  run prose_criterion     $T/general_criterion
  run rna_labels          $T/rna_labels
  run rna_mixed           $T/rna_mixed
  run retraction          $T/general_retraction
  echo "LANE $i DONE $(date)"
}
for i in 0 1 2; do lane $i > "$REPO/logs/${L}_lane$i.log" 2>&1 & done
wait
echo "CLAUDE_CODE_FULL_EXIT $(date)"
