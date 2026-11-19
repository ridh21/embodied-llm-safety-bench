#!/usr/bin/env bash
# Run the manipulation study for several models in parallel through an OpenAI-compatible router.
# Usage: NINEROUTER_KEY=... scripts/run_models.sh [preset] model1 model2 ...
# The key is read from the environment only; never put it in this file or on the command line.
set -euo pipefail
cd "$(dirname "$0")/.."
PRESET="${1:-pilot}"; shift
mkdir -p results/manip/logs
for m in "$@"; do
  slug="${m//[:\/]/_}"
  .venv/bin/python -W ignore -m saydo.manip.run --planner "$m" --api-key-env NINEROUTER_KEY \
      --preset "$PRESET" --conditions SAY DO DO_EVAL --workers "${WORKERS:-4}" > "results/manip/logs/${slug}.log" 2>&1 &
done
wait
