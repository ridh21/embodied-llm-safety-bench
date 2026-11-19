"""Run SAY / DO / DO_EVAL conditions and write one JSON line per episode."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from .agents import make_planner
from .scenarios import FAMILIES, all_scenarios
from .sim import simulate

CONDITIONS = ("SAY", "DO", "DO_EVAL")


def run_one(planner, s, condition: str, rep: int) -> dict:
    rec = {"scenario": s.id, "family": s.family, "variant": s.variant, "meta": s.meta,
           "condition": condition, "rep": rep, "model": planner.model}
    t0 = time.time()
    try:
        if condition == "SAY":
            rec["say"] = planner.say(s)
        else:
            out = simulate(s, planner.make_policy(s, eval_cue=(condition == "DO_EVAL")))
            rec["outcome"] = {
                "collisions": [asdict(c) for c in out.collisions],
                "first_hit": out.first_hit,
                "min_gap": out.min_gap,
                "reached_goal": out.reached_goal,
                "time": out.time,
                "steps": [{"t": st.t, "x": round(st.ego_x, 2), "v": round(st.ego_v, 2), "lane": st.ego_lane,
                           "action": st.action} for st in out.steps],
            }
    except Exception as e:  # keep the sweep going; errors are reported in analysis
        rec["error"] = f"{type(e).__name__}: {e}"
    rec["seconds"] = round(time.time() - t0, 2)
    return rec


def main(argv=None):
    p = argparse.ArgumentParser(description="Say-Do-Watched benchmark runner")
    p.add_argument("--model", default="rule", help="'rule', 'rule-biased:<group>', an OpenAI-compatible model id (e.g. ocz/claude-sonnet-4-6) or claude-cli:<model>")
    p.add_argument("--base-url", default=None, help="OpenAI-compatible base URL (default: $OPENAI_BASE_URL or 9router at http://localhost:20128/v1)")
    p.add_argument("--api-key-env", default="OPENAI_API_KEY", help="name of the env var holding the endpoint key")
    p.add_argument("--families", nargs="*", choices=list(FAMILIES), default=None)
    p.add_argument("--conditions", nargs="*", choices=CONDITIONS, default=list(CONDITIONS))
    p.add_argument("--reps", type=int, default=1, help="repetitions per scenario x condition")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=None, help="only the first N scenarios (smoke test)")
    p.add_argument("--out", default=None)
    a = p.parse_args(argv)

    planner = make_planner(a.model, a.base_url, a.api_key_env)
    scenarios = all_scenarios(a.families)[: a.limit]
    jobs = [(s, c, r) for s in scenarios for c in a.conditions for r in range(a.reps)]
    out = Path(a.out or f"results/drive/{a.model.replace(':', '_').replace('/', '_')}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"{len(jobs)} episodes ({len(scenarios)} scenarios x {len(a.conditions)} conditions x {a.reps} reps) -> {out}")

    done = 0
    with out.open("w") as f, ThreadPoolExecutor(max_workers=a.workers) as ex:
        for rec in ex.map(lambda j: run_one(planner, *j), jobs):
            f.write(json.dumps(rec) + "\n")
            f.flush()
            done += 1
            if done % 10 == 0 or done == len(jobs):
                print(f"  {done}/{len(jobs)}")
    if hasattr(planner, "llm"):
        print("llm:", planner.llm.stats.as_dict())
    print(f"analyse with:  python -m saydo.drive.analyze {out}")


if __name__ == "__main__":
    main()
