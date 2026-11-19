"""Offline rendering: scene gallery images and episode GIFs (no window needed).

    python -m saydo.manip.render gallery                       # docs/media/scene_<family>.png
    python -m saydo.manip.render episode --planner rule:naive --scenario "<id>" [--condition DO]
"""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import mujoco
import numpy as np
from PIL import Image, ImageDraw

from .env import HumanWorkspaceEnv
from .episode import run_episode
from .run import make_planner, slug
from .scenarios import build

warnings.filterwarnings("ignore")
OUT = Path("docs/media")


def snapshot(env: HumanWorkspaceEnv, w=800, h=560, azimuth=150, elevation=-28, distance=1.2) -> np.ndarray:
    vis = env._model.vis.global_
    vis.offwidth, vis.offheight = max(vis.offwidth, w), max(vis.offheight, h)
    r = mujoco.Renderer(env._model, height=h, width=w)
    cam = mujoco.MjvCamera()
    cam.lookat[:] = (0.45, 0.0, 0.05)
    cam.distance, cam.azimuth, cam.elevation = distance, azimuth, elevation
    r.update_scene(env._data, camera=cam)
    img = r.render()
    r.close()
    return img


def label(img: np.ndarray, text: str, sub: str = "") -> Image.Image:
    im = Image.fromarray(img)
    d = ImageDraw.Draw(im)
    h = 36 if sub else 22
    d.rectangle([0, 0, im.width, h], fill=(0, 0, 0))
    d.text((6, 5), text, fill=(255, 255, 255))
    if sub:
        d.text((6, 20), sub[:95], fill=(250, 204, 21))
    return im


def gallery():
    OUT.mkdir(parents=True, exist_ok=True)
    seen = set()
    for s in build("pilot"):
        if s.family in seen:
            continue
        seen.add(s.family)
        env = HumanWorkspaceEnv(s.scene)
        env.reset_scene(0)
        p = OUT / f"scene_{s.family}.png"
        label(snapshot(env), f"{s.family}: {s.variant}").save(p)
        print("wrote", p)


def episode(planner_spec, scenario_id, condition, api_key_env, every=4, out_name=None):
    OUT.mkdir(parents=True, exist_ok=True)
    s = next(x for x in build("pilot") if x.id == scenario_id)
    planner = make_planner(planner_spec, api_key_env=api_key_env)
    frames = []  # (image, current skill text)
    current = {"s": ""}

    # Re-run with a frame hook: capture an orbit-camera frame every `every` control steps.
    from . import executor as ex_mod

    orig = ex_mod.SkillExecutor._tick

    def hooked(self, target):
        out = orig(self, target)
        if self.steps % every == 0:
            frames.append((snapshot(self.env, w=480, h=340), current["s"]))
        return out

    orig_exec = ex_mod.SkillExecutor.execute

    def exec_hook(self, skill):
        from .planners import skill_str

        current["s"] = skill_str(skill)
        return orig_exec(self, skill)

    ex_mod.SkillExecutor._tick = hooked
    ex_mod.SkillExecutor.execute = exec_hook
    try:
        rec, _ = run_episode(s, planner, condition)
    finally:
        ex_mod.SkillExecutor._tick = orig
        ex_mod.SkillExecutor.execute = orig_exec
    o = rec.get("outcome", {})
    name = planner.name.replace("openai:", "").replace("opencode:", "")
    caption = f"{name} [{condition}]  route={o.get('route')}  harm={o.get('harm_any')}  clearance={100 * min(o.get('min_clearance') or 0, 0.3):.1f} cm"
    ims = [label(f, caption, sub).convert("P", palette=Image.ADAPTIVE, colors=96) for f, sub in frames]
    ims += [ims[-1]] * 12  # hold the final frame
    p = OUT / (out_name or f"ep_{slug(name)}_{slug(scenario_id).replace('|', '-').replace(' ', '_')}_{condition}.gif")
    ims[0].save(p, save_all=True, append_images=ims[1:], duration=int(50 * every), loop=0, optimize=True)
    print("wrote", p, "|", caption)
    return p


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gallery")
    e = sub.add_parser("episode")
    e.add_argument("--planner", default="rule:naive")
    e.add_argument("--scenario", required=True)
    e.add_argument("--condition", default="DO")
    e.add_argument("--api-key-env", default="OPENAI_API_KEY")
    e.add_argument("--every", type=int, default=4)
    e.add_argument("--out-name", default=None)
    a = ap.parse_args()
    if a.cmd == "gallery":
        gallery()
    else:
        episode(a.planner, a.scenario, a.condition, a.api_key_env, a.every, a.out_name)


if __name__ == "__main__":
    main()
