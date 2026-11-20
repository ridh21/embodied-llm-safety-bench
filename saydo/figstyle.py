"""Paper-figure style for matplotlib: Graphik + Tailwind v4 colours.

Usage
-----
    import figstyle as fs
    fs.use()                                   # fonts + rcParams
    ax.bar(x, y, **fs.bar_style("blue"))       # 400 fill, 600 outline
    ax.plot(t, y, color=fs.line("amber"))      # 600 line
    im = ax.imshow(z, cmap=fs.seq("blue"))     # one-hue sequential map
    im = ax.imshow(d, cmap=fs.div(), norm=fs.centered(d))  # diverging around 0
    fs.save(fig, "figures/fig1")               # writes .pdf (vector) + .png

Rules baked in (from https://www.sophielwang.com/blog/paper-writing):
* sans-serif labels (Graphik), weight for emphasis, monospace (B612 Mono) for literals
* a fixed colour per *entity* across every figure (see ``roles``)
* comparable elements share a shade level: fill 400 / outline 600
* sequential maps for ordered values, diverging only around a meaningful midpoint
* vector export with text kept as text
"""
from __future__ import annotations

import glob
import os

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

try:
    from .tailwind_v4 import TW  # type: ignore
except ImportError:
    from tailwind_v4 import TW

# Wide-hue default order: neighbours differ strongly in hue *and* lightness.
CATEGORICAL = ["blue", "amber", "emerald", "rose", "violet", "cyan", "lime", "fuchsia"]
NEUTRAL = "slate"

INK = TW["slate"][900]
INK_2 = TW["slate"][600]
MUTED = TW["slate"][400]
GRID = TW["slate"][200]
SURFACE = "#ffffff"

# Search the fonts bundled next to this file first (keeps the skill portable),
# then an optional env override, then the usual system locations.
_FONT_DIRS = [d for d in [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts"),
    os.environ.get("FIGSTYLE_FONTS", ""),
    os.path.expanduser("~/Library/Fonts"), "/Library/Fonts",
    os.path.expanduser("~/.fonts"), "/usr/share/fonts",
] if d]


def _register(pattern: str) -> bool:
    found = False
    for d in _FONT_DIRS:
        for f in glob.glob(os.path.join(d, "**", pattern), recursive=True):
            font_manager.fontManager.addfont(f)
            found = True
    return found


def use(base_size: float = 9.0, sans: str = "Graphik", mono: str = "B612 Mono") -> None:
    """Register fonts and set rcParams. Falls back gracefully if a font is missing."""
    has_sans = _register(f"{sans.replace(' ', '')}*.[ot]tf") or _register(f"{sans}*.[ot]tf")
    has_mono = _register(f"{mono.replace(' ', '')}*.[ot]tf") or _register(f"{mono.replace(' ', '_')}*.[ot]tf")
    sans_stack = ([sans] if has_sans else []) + ["Inter", "Helvetica Neue", "Arial", "DejaVu Sans"]
    mono_stack = ([mono] if has_mono else []) + ["Menlo", "DejaVu Sans Mono"]
    installed = {f.name for f in font_manager.fontManager.ttflist}
    sans_stack = [f for f in sans_stack if f in installed] or ["DejaVu Sans"]
    mono_stack = [f for f in mono_stack if f in installed] or ["DejaVu Sans Mono"]
    mpl.rcParams.update({
        # a list of real family names enables per-glyph fallback (Graphik lacks σ, π, arrows)
        "font.family": sans_stack,
        "font.sans-serif": sans_stack,
        "font.monospace": mono_stack,
        "font.size": base_size,
        "axes.titlesize": base_size + 1,
        "axes.titleweight": "medium",
        "axes.titlelocation": "left",
        "axes.titlepad": 8,
        "axes.labelsize": base_size,
        "axes.labelcolor": INK_2,
        "axes.edgecolor": TW["slate"][300],
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": False,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "axes.prop_cycle": mpl.cycler(color=[TW[h][500] for h in CATEGORICAL]),
        "xtick.color": MUTED, "ytick.color": MUTED,
        "xtick.labelcolor": INK_2, "ytick.labelcolor": INK_2,
        "xtick.labelsize": base_size - 1, "ytick.labelsize": base_size - 1,
        "xtick.major.size": 3, "ytick.major.size": 3,
        "xtick.major.width": 0.8, "ytick.major.width": 0.8,
        "legend.frameon": False,
        "legend.fontsize": base_size - 1,
        "legend.handlelength": 1.2,
        "lines.linewidth": 1.6,
        "lines.markersize": 4,
        "patch.linewidth": 0.8,
        "text.color": INK,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "figure.dpi": 110,
        "savefig.dpi": 220,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.05,
        "pdf.fonttype": 42,     # embed TrueType -> text stays selectable text
        "ps.fonttype": 42,
        "svg.fonttype": "none",
        "image.interpolation": "nearest",
        "mathtext.fontset": "custom",
        "mathtext.rm": sans_stack[0], "mathtext.it": f"{sans_stack[0]}:italic",
        "mathtext.bf": f"{sans_stack[0]}:bold",
    })


# ---------- colour helpers -------------------------------------------------
def c(hue: str, shade: int = 500) -> str:
    return TW[hue][shade]


def fill(hue: str) -> str:
    return TW[hue][400]


def edge(hue: str) -> str:
    return TW[hue][600]


def line(hue: str) -> str:
    return TW[hue][600]


def light(hue: str) -> str:
    return TW[hue][100]


def bar_style(hue: str, **kw) -> dict:
    """Same shade level for comparable elements: 400 fill, 600 outline."""
    return {"color": fill(hue), "edgecolor": edge(hue), "linewidth": 0.8, **kw}


def roles(names, hues=None) -> dict:
    """Fix one hue per entity (crop, method, condition) and reuse it everywhere."""
    hues = hues or CATEGORICAL
    return {n: hues[i % len(hues)] for i, n in enumerate(names)}


def cyclic() -> "Colormap":
    """For angles/phase only (data that wraps around). No Tailwind ramp is cyclic,
    so use matplotlib's perceptually uniform 'twilight'."""
    return plt.get_cmap("twilight")


def seq(hue: str = "blue", lo: int = 50, hi: int = 900) -> LinearSegmentedColormap:
    """One-hue sequential map. Tailwind shades are spaced in OKLCH lightness, so
    the ramp changes evenly in perceived colour."""
    shades = [s for s in TW[hue] if lo <= s <= hi]
    return LinearSegmentedColormap.from_list(f"tw_{hue}", [TW[hue][s] for s in shades])


def div(neg: str = "blue", pos: str = "red", mid: str = NEUTRAL) -> LinearSegmentedColormap:
    """Diverging map with a neutral midpoint. Use only when 0 (or a baseline) means something."""
    stops = [TW[neg][s] for s in (800, 600, 400, 200)] + [TW[mid][100]] + \
            [TW[pos][s] for s in (200, 400, 600, 800)]
    return LinearSegmentedColormap.from_list(f"tw_{neg}_{pos}", stops)


def centered(data, center: float = 0.0) -> TwoSlopeNorm:
    import numpy as np
    m = float(np.nanmax(np.abs(np.asarray(data) - center))) or 1.0
    return TwoSlopeNorm(vcenter=center, vmin=center - m, vmax=center + m)


# ---------- layout helpers -------------------------------------------------
def panel_label(ax, text: str, dx: float = -5, **_ignored) -> None:
    """Bold panel letter just left of the (left-aligned) title, on the title baseline,
    so it never collides with the title text."""
    ax.annotate(text, xy=(0, 1), xycoords="axes fraction",
                xytext=(dx, mpl.rcParams["axes.titlepad"]), textcoords="offset points",
                ha="right", va="baseline", fontsize=mpl.rcParams["axes.titlesize"] + 1,
                fontweight="bold", color=INK, annotation_clip=False)


def note(ax, text: str, x: float = 0.0, y: float = -0.18, **kw) -> None:
    """Small muted caption under an axis (for units, data caveats)."""
    ax.text(x, y, text, transform=ax.transAxes, fontsize=mpl.rcParams["font.size"] - 1.5,
            color=MUTED, va="top", ha="left", **kw)


def direct_label(ax, x, y, text: str, hue: str, dx: float = 4, **kw) -> None:
    """Label a series at its end instead of a legend. Text in ink, not series colour,
    unless the label *is* the identity cue for a thin line."""
    ax.annotate(text, (x, y), xytext=(dx, 0), textcoords="offset points",
                va="center", fontsize=mpl.rcParams["font.size"] - 0.5,
                color=TW[hue][700], fontweight="medium", **kw)


def clean_image_axes(ax) -> None:
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


def save(fig, path_no_ext: str, formats=("pdf", "png")) -> None:
    os.makedirs(os.path.dirname(path_no_ext) or ".", exist_ok=True)
    for f in formats:
        fig.savefig(f"{path_no_ext}.{f}")
    plt.close(fig)
