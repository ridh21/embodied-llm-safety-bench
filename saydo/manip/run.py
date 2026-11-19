"""Sweep runner for the manipulation study (resumable, parallel).

    python -m saydo.manip.run --planner rule:safe --preset pilot
    python -m saydo.manip.run --planner ocz/claude-sonnet-4-6 --api-key-env NINEROUTER_KEY --preset pilot
    python -m saydo.manip.run --planner claude-cli:sonnet --preset smoke --workers 4
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..llm import make_llm
from .episode import CONDITIONS, run_episode
from .planners import LLMPlanner, RulePlanner
from .scenarios import PRESETS, build


def make_planner(spec: str, base_url=None, api_key_env="OPENAI_API_KEY", temperature=None):
    if spec.startswith("rule:"):
        return RulePlanner(spec.split(":", 1)[1])
    return LLMPlanner(make_llm(spec, base_url=base_url, api_key_env=api_key_env, temperature=temperature))


def slug(s: str) -> str:
    return s.replace(":", "_").replace("/", "_")


def main(argv=None):
    p = argparse.ArgumentParser(description="Say-Do-Watched: embodied manipulation study runner")
    p.add_argument("--planner", required=True,
                   help="rule:safe | rule:naive | rule:biased:<group> | <openai-compatible model id> | claude-cli:<model>")
    p.add_argument("--base-url", default=None, help="OpenAI-compatible base URL (default $OPENAI_BASE_URL or 9router http://localhost:20128/v1)")
    p.add_argument("--api-key-env", default="OPENAI_API_KEY", help="env var holding the endpoint key (never pass keys on the command line)")
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--preset", default="pilot", choices=list(PRESETS))
    p.add_argument("--families", nargs="*", default=None)
    p.add_argument("--conditions", nargs="*", default=["SAY", "DO", "DO_EVAL"], choices=list(CONDITIONS))
    p.add_argument("--samples", type=int, default=1, help="independent samples per scenario x condition")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--out", default=None)
    a = p.parse_args(argv)

    planner = make_planner(a.planner, a.base_url, a.api_key_env, a.temperature)
    scenarios = build(a.preset, a.families)[: a.limit]
    out = Path(a.out or f"results/manip/{slug(a.planner)}__{a.preset}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)

    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "error" not in r:
                done.add((r["scenario"], r["condition"], r.get("sample", 0)))
    jobs = [(s, c, k) for s in scenarios for c in a.conditions for k in range(a.samples) if (s.id, c, k) not in done]
    print(f"{planner.name}: {len(scenarios)} scenarios x {len(a.conditions)} conditions x {a.samples} samples; "
          f"{len(done)} already done, {len(jobs)} to run -> {out}", flush=True)

    lock = threading.Lock()
    t0 = time.time()
    n_err = 0
    with out.open("a") as f, ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(run_episode, s, planner, c, 0, k) for s, c, k in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            rec, _ = fut.result()
            n_err += "error" in rec
            with lock:
                f.write(json.dumps(rec) + "\n")
                f.flush()
            if i % 10 == 0 or i == len(jobs):
                el = time.time() - t0
                print(f"  {i}/{len(jobs)}  errors={n_err}  {el / 60:.1f} min elapsed, ~{el / i * (len(jobs) - i) / 60:.1f} min left", flush=True)
    if isinstance(planner, LLMPlanner):
        print("llm stats:", planner.llm.stats.as_dict())
    print(f"analyse:  python -m saydo.manip.analyze {out}")
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
