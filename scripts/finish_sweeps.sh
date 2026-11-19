#!/usr/bin/env bash
# Wait for running sweeps, then do one resume pass per model to retry transient failures.
cd "$(dirname "$0")/.."
while pgrep -f "saydo.manip.run --planner" >/dev/null; do sleep 30; done
for m in "$@"; do
  slug="${m//[:\/]/_}"
  echo "== resume pass: $m"
  .venv/bin/python -W ignore -m saydo.manip.run --planner "$m" --api-key-env NINEROUTER_KEY --preset pilot \
      --conditions SAY DO DO_EVAL --workers 4 >> "results/manip/logs/${slug}.resume.log" 2>&1
  tail -2 "results/manip/logs/${slug}.resume.log"
done
