#!/bin/zsh
# Build the VisText-Health workspaces into tasks/health/ with generators/make_health.py.
#
# Six published health and public-health series from VisText, in atlases of 30 to 60 charts,
# with three kinds of transition: overwrite a value, delete an entity, or both. Three of the
# series admit only `overwrite`, because `delete` and `multi` need a chart that stays plausible
# after losing a row and whose runner-up is still outranked by a peer chart afterwards.
#
# The paper's generation also built h-11 and h-12 from a seventh series (deaths related to
# coronavirus, 40 and 60 charts); they are not part of the benchmark because their corrected
# reference captions are stale, so they are not built here.
#
# Each build asserts the P1-P6 construction contract and exits non-zero if it fails. The released
# tasks/health was built with an earlier revision of the generator and is not reproduced byte for
# byte.
set -e
cd "$(dirname "$0")/.."   # repository root
PY=${PYTHON:-python3}
LOG=${TMPDIR:-/tmp}

# Two pool records carry the same anxiety-prevalence title and only one passes the caption
# gate, so a title match can be ambiguous; such a series is selected by image id instead.
# make_health.py refuses an ambiguous match.
build () {   # id  selector(title-regex or id:NNNN)  charts  mode
  local id=$1 rx=$2 n=$3 mode=$4 sel
  case "$rx" in id:*) sel="--img-id ${rx#id:}";; *) sel="--title-match $rx";; esac
  for seed in 0 1 2 3 4 5 6 7; do
    if $PY generators/make_health.py --id "$id" ${=sel} --charts "$n" --mode "$mode" \
         --seed "$seed" > $LOG/make_health_$id.log 2>&1; then
      printf '%-6s %-9s n=%-3s seed=%-2s %s\n' "$id" "$mode" "$n" "$seed" \
             "$(grep -m1 '^target' $LOG/make_health_$id.log | cut -c1-70)"
      return 0
    fi
  done
  echo "FAILED $id ($rx, $n, $mode)"; tail -3 $LOG/make_health_$id.log; return 1
}

build h-01 'opioid-related emergency'        30 overwrite
build h-02 'opioid-related emergency'        40 delete
build h-03 'opioid-related emergency'        50 multi
build h-04 'cases in the Eastern Mediterranean' 30 delete
build h-05 'cases in the Eastern Mediterranean' 40 multi
build h-06 'cases in the Eastern Mediterranean' 60 delete
build h-07 'Cost of an angioplasty'          50 delete
build h-08 'Cost of an angioplasty'          60 overwrite
build h-09 'nurses in registered nursing'    30 overwrite
build h-10 'nurses in registered nursing'    50 overwrite
build h-13 'deaths from drowning'            30 overwrite
build h-14 'deaths from drowning'            50 overwrite
build h-15 id:7772                           40 overwrite
build h-16 id:7772                           60 overwrite
echo BUILD_DONE
