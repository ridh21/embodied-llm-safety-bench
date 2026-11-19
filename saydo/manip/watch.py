"""Watch an episode live in the interactive MuJoCo viewer.

macOS needs MuJoCo's `mjpython` launcher for the viewer window:

    .venv/bin/mjpython -m saydo.manip.watch --list                         # list scenario ids
    .venv/bin/mjpython -m saydo.manip.watch --planner rule:naive --family pass_by
    .venv/bin/mjpython -m saydo.manip.watch --planner rule:safe  --scenario "dilemma::L0::an adult man|an adult man#o0"
    NINEROUTER_KEY=... .venv/bin/mjpython -m saydo.manip.watch --planner ag/claude-sonnet-4-6 \
        --api-key-env NINEROUTER_KEY --family handover --index 4

Mouse: left-drag rotate, right-drag pan, scroll zoom. The planner's current skill and reasoning are
shown in the window and printed to the terminal. Model replies are cached, so replaying a scenario
the sweep already ran costs nothing.
"""

from __future__ import annotations

import argparse
import textwrap
import time
import warnings

import mujoco
import mujoco.viewer

from .episode import score
from .env import HumanWorkspaceEnv
from .executor import SkillExecutor
from .planners import RulePlanner, skill_str
from .run import make_planner
from .scenarios import PRESETS, build

warnings.filterwarnings("ignore")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--planner", default="rule:safe")
    p.add_argument("--base-url", default=None)
    p.add_argument("--api-key-env", default="OPENAI_API_KEY")
    p.add_argument("--preset", default="pilot", choices=list(PRESETS))
    p.add_argument("--family", default=None)
    p.add_argument("--index", type=int, default=0, help="which scenario of the family")
    p.add_argument("--scenario", default=None, help="exact scenario id (see --list)")
    p.add_argument("--condition", default="DO", choices=["DO", "DO_EVAL", "DO_SHIELD"])
    p.add_argument("--speed", type=float, default=1.0, help="playback speed multiplier")
    p.add_argument("--list", action="store_true")
    p.add_argument("--hold", type=float, default=30.0, help="seconds to keep the window open at the end")
    a = p.parse_args(argv)

    scs = build(a.preset)
    if a.list:
        for s in scs:
            print(s.id)
        return
    if a.scenario:
        sc = next(s for s in scs if s.id == a.scenario)
    else:
        fam = [s for s in scs if a.family is None or s.family == a.family]
        sc = fam[a.index % len(fam)]

    planner = make_planner(a.planner, a.base_url, a.api_key_env)
    env = HumanWorkspaceEnv(sc.scene)
    env.reset_scene(0)
    ex = SkillExecutor(env, shield=(a.condition == "DO_SHIELD"))
    eval_cue = a.condition == "DO_EVAL"

    print(f"\nScenario: {sc.id}\nTask: {sc.task}\nPlanner: {planner.name}   Condition: {a.condition}\n")
    with mujoco.viewer.launch_passive(env._model, env._data, show_left_ui=False, show_right_ui=False) as v:
        v.cam.lookat[:] = (0.45, 0.0, 0.05)
        v.cam.distance, v.cam.azimuth, v.cam.elevation = 1.25, 150, -28
        status = {"text": "starting"}

        def show():
            try:
                v.set_texts([(mujoco.mjtFontScale.mjFONTSCALE_150, mujoco.mjtGridPos.mjGRID_TOPLEFT,
                              f"{planner.name}  [{a.condition}]  t={env.t:4.1f}s", status["text"])])
            except Exception:
                pass

        tick = ex._tick

        def live_tick(target):  # real-time playback hook
            t0 = time.time()
            out = tick(target)
            show()
            v.sync()
            time.sleep(max(0.0, 0.05 / a.speed - (time.time() - t0)))
            return out

        ex._tick = live_tick
        time.sleep(1.0)
        history = []
        plan = iter(planner.plan(sc, eval_cue)) if isinstance(planner, RulePlanner) else None
        for _ in range(sc.max_skills):
            if not v.is_running():
                return
            status["text"] = "thinking..."
            show(); v.sync()
            d = next(plan, {"skill": "done"}) if plan else planner.decide(sc, env, history, eval_cue)
            reason = d.get("reasoning", "")
            status["text"] = skill_str(d) + ("\n" + "\n".join(textwrap.wrap(reason, 70)) if reason else "")
            print(f"[{env.t:5.1f}s] {skill_str(d)}" + (f"\n         {reason}" if reason else ""))
            fb = ex.execute(d)
            history.append({"skill_str": skill_str(d), "feedback": fb})
            print(f"         -> {fb}")
            if d.get("skill") in ("abort", "done"):
                break
        o = score(sc, env, ex, aborted=d.get("skill") == "abort")
        summary = (f"success={o['success']}  route={o['route']}  harm={o['harm_any']}  "
                   f"min clearance={o['min_clearance'] * 100:.1f} cm  vase damaged={o['vase_damaged']}")
        print("\nRESULT:", summary)
        status["text"] = "RESULT\n" + summary.replace("  ", "\n")
        end = time.time() + a.hold
        while v.is_running() and time.time() < end:
            show(); v.sync()
            time.sleep(0.05)


if __name__ == "__main__":
    main()
