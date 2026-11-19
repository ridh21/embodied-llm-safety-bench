#!/usr/bin/env bash
# Finish the Claude sweeps through 9router (cc/ = 9router's Claude accounts).
# Repeats resume passes until nothing is left to run, waiting between passes on rate limits.
# Usage: NINEROUTER_KEY=... scripts/claude_9router.sh
cd "$(dirname "$0")/.."
run_model() {
  local m="$1" slug="${1//[:\/]/_}"; local log="results/manip/logs/${slug}.9router.log"
  for pass in 1 2 3 4 5 6 7 8; do
    echo "== pass $pass $(date +%T)" >> "$log"
    .venv/bin/python -W ignore -m saydo.manip.run --planner "$m" --api-key-env NINEROUTER_KEY --preset pilot \
        --conditions SAY DO DO_EVAL --workers 3 >> "$log" 2>&1
    local code=$?
    grep -q " 0 to run" <(grep "to run" "$log" | tail -1) && { echo "== complete" >> "$log"; return; }
    [ $code -eq 0 ] && { echo "== pass clean" >> "$log"; }
    [ $code -eq 3 ] && { echo "== quota exhausted, waiting 30 min" >> "$log"; sleep 1800; continue; }
    sleep 120
  done
}
run_model cc/claude-sonnet-5 &
run_model cc/claude-opus-5-5 &
wait
