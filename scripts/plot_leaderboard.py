#!/usr/bin/env python
"""JobBench-style horizontal bar charts for the biology_bench leaderboard.

Renders one chart per metric (mean score, pass@0.7 accuracy) with each
backend's logo next to its name, dark theme, the omicos bar highlighted.

Data source: reports/final/matrix.csv (written by _assemble_final.py) — long
form `backend,task,score,status,...`. Aggregates to per-backend mean + pass
rate over cells that actually ran (status != unavailable). Re-run
_assemble_final.py first so the numbers are current.

Logos: logos/<backend>.png (transparent, roughly square). Missing logo →
name only, no crash.

Usage:
    python scripts/plot_leaderboard.py            # both charts
    python scripts/plot_leaderboard.py mean       # just mean
    python scripts/plot_leaderboard.py accuracy
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
# Prefer the dual-judge matrix (deepseek + gemini per-cell averaged) when present,
# so the headline chart is robust to the choice of judge; fall back to the
# DeepSeek-only matrix otherwise.
MATRIX_DUAL = ROOT / "reports" / "final" / "matrix_dualjudge.csv"
MATRIX_DS = ROOT / "reports" / "final" / "matrix.csv"
MATRIX = MATRIX_DUAL if MATRIX_DUAL.is_file() else MATRIX_DS
SCORE_COL = "dual_mean" if MATRIX is MATRIX_DUAL else "score"
LOGO_DIR = ROOT / "logos"
OUT_DIR = ROOT / "reports" / "final"
PASS = 0.70

# Display name + logo file per backend id, in no particular order (charts sort
# by the metric). Keep names short so the left gutter stays tight.
DISPLAY = {
    "omicos":             ("OmicOS",                         "omicos.png"),
    "biomni":             ("Biomni (OSS)",                   "biomni.png"),
    "claude_csswitch":    ("Claude/CSSwitch",                "claude.png"),
    "evoscientist":       ("EvoScientist",                   "evoscientist.png"),
    "openscience_ai4s":   ("ai4s-research/open-science",     "ai4s.png"),
    "openscience_synsci": ("synthetic-sciences/openscience", "synsci.png"),
    "wisp":               ("Wisp Science",                   "wisp.png"),
}
HIGHLIGHT = "omicos"

# Small gray sub-line under a backend's name (clarifications). Combined with the
# partial "(n/50)" indicator when a backend hasn't finished all 50 tasks.
SUBNOTE = {
    "biomni": "open-source version (snap-stanford/Biomni)",
}

# Underlying agent engine each backend wraps. Two backends are thin wrappers
# over a shared engine (Claude Code / OpenCode); the rest ship an independent
# engine. Rendered as a symbol after the name + decoded in the bottom legend.
ENGINE = {
    "omicos":             "●",   # independent (omicos-core)
    "biomni":             "●",   # independent (Biomni A1)
    "evoscientist":       "●",   # independent (EvoScientist)
    "openscience_synsci": "●",   # independent (OpenScience CLI)
    "wisp":               "●",   # independent (Wisp native)
    "claude_csswitch":    "◆",   # Claude Code core
    "openscience_ai4s":   "▲",   # OpenCode core
}
ENGINE_LEGEND = ("Engine core:    ◆ Claude Code       ▲ OpenCode       "
                 "● independent / self-built")

# JobBench-ish palettes (dark + light/white-bg). Highlight = OmicVerse dark green.
THEMES = {
    "dark":  dict(bg="#0b0b0d", bar="#3a3a3e", bar_hi="#1f9d57",
                  text="#f2f2f4", subtext="#9a9aa2", hi_text="#9fe3bd"),
    "light": dict(bg="#ffffff", bar="#e4e4ea", bar_hi="#137a45",
                  text="#17171b", subtext="#6b6b73", hi_text="#0e5c34"),
}
# Logos that are white/transparent → invisible on a white background, so recolor
# them to a dark navy for the light theme.
WHITE_LOGOS = {"omicos", "wisp", "openscience_synsci"}
LIGHT_LOGO_RGB = (26, 40, 72)


def load_stats():
    """backend -> (n, mean, pass_rate_pct).

    Mean = dual-judge per-cell mean when the dual matrix is present (robust to
    judge choice). Pass@0.70 stays on the single reproducible DeepSeek score —
    thresholding a two-judge average near the 0.70 boundary is noisy, so the
    accuracy chart keeps the authoritative DeepSeek pass rate.
    """
    mean_v = defaultdict(list)   # dual_mean (or score, if only the DS matrix)
    pass_v = defaultdict(list)   # deepseek score for the pass@0.70 metric
    with MATRIX.open() as f:
        for r in csv.DictReader(f):
            if r.get("status") == "unavailable":
                continue
            try:
                mean_v[r["backend"]].append(float(r[SCORE_COL]))
                pass_v[r["backend"]].append(float(r.get("deepseek", r.get("score"))))
            except (KeyError, ValueError, TypeError):
                continue
    out = {}
    for b, ss in mean_v.items():
        n = len(ss)
        if not n:
            continue
        ps = pass_v[b]
        out[b] = (n, sum(ss) / n, 100.0 * sum(1 for s in ps if s >= PASS) / len(ps))
    return out


def _logo(backend, theme, target_h_px=120):
    p = LOGO_DIR / DISPLAY[backend][1]
    if not p.is_file():
        return None
    try:
        im = Image.open(p).convert("RGBA")
        if theme == "light" and backend in WHITE_LOGOS:
            # recolor near-white pixels to navy so the logo shows on white,
            # leaving distinctly-colored accents (e.g. wisp's maroon dot) alone
            import numpy as np
            a = np.array(im)
            rgb = a[..., :3].astype(int)
            near_white = (rgb.min(axis=-1) > 170) & (np.ptp(rgb, axis=-1) < 45)
            a[near_white, 0], a[near_white, 1], a[near_white, 2] = LIGHT_LOGO_RGB
            im = Image.fromarray(a)
        w, h = im.size
        scale = target_h_px / h
        im = im.resize((max(1, int(w * scale)), target_h_px), Image.LANCZOS)
        return im
    except Exception:
        return None


def plot(metric: str, stats: dict, theme: str = "dark"):
    # metric: 'mean' -> value 0..1 (2 decimals); 'accuracy' -> percent
    P = THEMES[theme]
    idx = 1 if metric == "mean" else 2
    items = sorted(stats.items(), key=lambda kv: kv[1][idx], reverse=True)

    ns = [v[0] for _, v in items]
    vals = [v[idx] for _, v in items]
    axmax = (1.0 if metric == "mean" else 100.0)

    n = len(items)
    fig_h = 0.72 * n + 2.5
    fig, ax = plt.subplots(figsize=(11.5, fig_h), dpi=200)
    fig.patch.set_facecolor(P["bg"])
    ax.set_facecolor(P["bg"])

    y = list(range(n))[::-1]  # top row first
    for yi, (b, _), val in zip(y, items, vals):
        color = P["bar_hi"] if b == HIGHLIGHT else P["bar"]
        ax.barh(yi, val, height=0.52, color=color, zorder=2, edgecolor="none")
        vtxt = f"{val:.3f}" if metric == "mean" else f"{val:.1f}"
        ax.text(val + axmax * 0.012, yi, vtxt, va="center", ha="left",
                color=P["text"], fontsize=13, fontweight="bold", zorder=4)

    # left gutter: logo (far left) + name (left-aligned) then bar from x=0.
    gutter = 0.86
    logo_x = -axmax * (gutter - 0.03)
    name_x = -axmax * (gutter - 0.10)
    badges = []  # (name text obj, symbol, fontsize) — placed after limits are set
    for yi, (b, _), nn in zip(y, items, ns):
        name = DISPLAY.get(b, (b, ""))[0]
        fs = 14 if len(name) <= 15 else (11.5 if len(name) <= 24 else 10)
        t = ax.text(name_x, yi, name, va="center", ha="left",
                    color=P["hi_text"] if b == HIGHLIGHT else P["text"],
                    fontsize=fs, fontweight="bold", zorder=4)
        if b in ENGINE:
            badges.append((t, ENGINE[b], fs))
        parts = []
        if b in SUBNOTE:
            parts.append(SUBNOTE[b])
        if nn < 50:
            parts.append(f"{nn}/50")
        if parts:
            ax.text(name_x, yi - 0.34, " · ".join(parts), va="center",
                    ha="left", color=P["subtext"], fontsize=8.5, zorder=4)
        im = _logo(b, theme)
        if im is not None:
            ab = AnnotationBbox(OffsetImage(im, zoom=0.18), (logo_x, yi),
                                frameon=False, box_alignment=(0.5, 0.5),
                                xycoords="data", zorder=5)
            ax.add_artist(ab)

    ax.set_xlim(-axmax * (gutter + 0.02), axmax * 1.14)
    ax.set_ylim(-1.7, n - 0.15)
    ax.axis("off")

    # engine badges: superscript at each name's upper-right. Measure AFTER the
    # limits are set + a draw, so transData maps display→data correctly.
    fig.canvas.draw()
    inv = ax.transData.inverted()
    r = fig.canvas.get_renderer()
    for t, sym, fs in badges:
        bb = t.get_window_extent(renderer=r)
        x_r, y_t = inv.transform((bb.x1, bb.y1))
        ax.annotate(sym, (x_r, y_t), xytext=(3, 1), textcoords="offset points",
                    va="bottom", ha="left", fontsize=fs * 0.62,
                    fontweight="bold", color=P["subtext"], zorder=5)

    dual = MATRIX is MATRIX_DUAL
    tx = -axmax * (gutter + 0.02)
    if metric == "mean":
        title = ("BiomniBench-DA — dual-judge mean rubric score" if dual
                 else "BiomniBench-DA — mean rubric score")
        caption = ("50 tasks · mean of two judges (DeepSeek v4-pro + Gemini 3.1 "
                   "Pro) · all backends deepseek-v4-pro" if dual else
                   "50 tasks · DeepSeek v4-pro judge · all backends deepseek-v4-pro")
    else:
        title = "BiomniBench-DA — pass@0.70 accuracy (%)"
        caption = ("50 tasks · pass@0.70 on the DeepSeek v4-pro judge · all "
                   "backends deepseek-v4-pro")
    ax.text(tx, n - 0.05, title, ha="left", va="bottom",
            color=P["text"], fontsize=15, fontweight="bold")

    # bottom caption / legend
    ax.text(tx, -1.05, caption,
            ha="left", va="center", color=P["subtext"], fontsize=9.5)
    ax.text(tx, -1.45, ENGINE_LEGEND, ha="left", va="center",
            color=P["subtext"], fontsize=9.5)

    suffix = "" if theme == "dark" else f"_{theme}"
    out = OUT_DIR / f"leaderboard_{metric}{suffix}.png"
    fig.savefig(out, facecolor=P["bg"], bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)
    print(f"-> {out}")
    return out


def main():
    if not MATRIX.is_file():
        sys.exit(f"no {MATRIX}; run _assemble_final.py first")
    stats = load_stats()
    args = [a for a in sys.argv[1:]]
    which = [a for a in args if a in ("mean", "accuracy")] or ["mean", "accuracy"]
    # theme filter: pass 'dark' or 'light' to restrict; default = both
    themes = [t for t in ("dark", "light") if t in args] or ["dark", "light"]
    for m in which:
        for t in themes:
            plot(m, stats, t)


if __name__ == "__main__":
    main()
