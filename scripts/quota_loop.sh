#!/usr/bin/env bash
# Keep a sweep going across free-tier quota resets (e.g. OpenCode free models).
# When the provider reports its quota is used up, the sweep stops cleanly (exit 3); this loop then
# probes every 60 s and resumes as soon as calls succeed again (e.g. after switching VPN server).
# Usage: scripts/quota_loop.sh opencode:opencode/deepseek-v4.1-flash-free [preset]
cd "$(dirname "$0")/.."
M="$1"; PRESET="${2:-pilot}"; slug="${M//[:\/]/_}"; LOG="results/manip/logs/${slug}.loop.log"
probe() { .venv/bin/python -W ignore -c "
import sys; from saydo.llm import make_llm
l=make_llm(sys.argv[1]); l.cache=False; l.retries=1
l.complete_json('ok','Reply ok.',{'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False})" "$M" >/dev/null 2>&1; }
while true; do
  .venv/bin/python -W ignore -m saydo.manip.run --planner "$M" --preset "$PRESET" --conditions SAY DO DO_EVAL --workers 5 >> "$LOG" 2>&1
  code=$?
  if grep -q " 0 to run" <(tail -5 "$LOG"); then echo "$(date +%T) complete"; break; fi
  if [ $code -eq 3 ]; then
    echo "$(date +%T) quota exhausted: waiting for reset (switch VPN server to speed this up)"
    until probe; do sleep 60; done
    echo "$(date +%T) quota available again, resuming"
  elif [ $code -eq 0 ]; then echo "$(date +%T) sweep pass finished with no errors"; break
  else echo "$(date +%T) pass ended with transient errors, retrying"; sleep 10; fi
done
