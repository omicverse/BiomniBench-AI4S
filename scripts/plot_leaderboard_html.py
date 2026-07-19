#!/usr/bin/env python
"""Animated HTML leaderboard — bars grow in sequence, scores count up.

Self-contained single file (logos base64-embedded, no external deps), so it can
be opened locally or dropped anywhere. Mirrors the PNG charts' style: dark
theme, per-backend logo + engine badge, OmicOS highlighted in OmicVerse green.

Data: reports/final/matrix_dualjudge.csv (dual-judge per-cell mean → per-backend
mean). Usage:  python scripts/plot_leaderboard_html.py
"""
import base64
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "reports" / "final" / "matrix_dualjudge.csv"
LOGO_DIR = ROOT / "logos"
OUT = ROOT / "reports" / "final" / "leaderboard_mean.html"

DISPLAY = {
    "omicos":             ("OmicOS",                         "omicos.png"),
    "biomni":             ("Biomni (OSS)",                   "biomni.png"),
    "claude_csswitch":    ("Claude / CSSwitch",              "claude.png"),
    "evoscientist":       ("EvoScientist",                   "evoscientist.png"),
    "openscience_ai4s":   ("ai4s-research/open-science",     "ai4s.png"),
    "openscience_synsci": ("synthetic-sciences/openscience", "synsci.png"),
    "wisp":               ("Wisp Science",                   "wisp.png"),
}
SUBNOTE = {"biomni": "open-source version (snap-stanford/Biomni)"}
ENGINE = {"omicos": "●", "biomni": "●", "evoscientist": "●",
          "openscience_synsci": "●", "wisp": "●",
          "claude_csswitch": "◆", "openscience_ai4s": "▲"}
ENGINE_LEGEND = ("Engine core:&nbsp;&nbsp; ◆ Claude Code &nbsp;&nbsp; ▲ OpenCode "
                 "&nbsp;&nbsp; ● independent / self-built")
HIGHLIGHT = "omicos"
GREEN = "#1f9d57"
BAR = "#3a3a3e"


def load_means():
    rows = defaultdict(list)
    with MATRIX.open() as f:
        for r in csv.DictReader(f):
            if r.get("status") == "unavailable":
                continue
            try:
                rows[r["backend"]].append(float(r["dual_mean"]))
            except (KeyError, ValueError):
                continue
    out = {b: (len(v), sum(v) / len(v)) for b, v in rows.items() if v}
    return sorted(out.items(), key=lambda kv: kv[1][1], reverse=True)


def logo_uri(fname):
    p = LOGO_DIR / fname
    if not p.is_file():
        return ""
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f"data:image/png;base64,{b64}"


def build():
    items = load_means()
    axmax = 1.0
    rows_html = []
    for i, (b, (n, val)) in enumerate(items):
        name, logo = DISPLAY.get(b, (b, ""))
        hi = b == HIGHLIGHT
        eng = ENGINE.get(b, "")
        sub = SUBNOTE.get(b, "")
        uri = logo_uri(logo)
        pct = val / axmax * 100.0
        rows_html.append(f"""
      <div class="row{' hi' if hi else ''}" style="--i:{i}; --pct:{pct:.2f}%;">
        <div class="label">
          <span class="logo">{f'<img src="{uri}" alt="">' if uri else ''}</span>
          <span class="nm">{name}<sup class="eng">{eng}</sup>
            {f'<span class="sub">{sub}</span>' if sub else ''}
          </span>
        </div>
        <div class="track"><div class="bar"></div></div>
        <div class="val" data-v="{val:.3f}">0.000</div>
      </div>""")
    rows_joined = "".join(rows_html)
    n_rows = len(items)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BiomniBench-DA — dual-judge mean leaderboard</title>
<style>
  :root {{
    --bg:#0b0b0d; --text:#f2f2f4; --sub:#9a9aa2; --bar:{BAR}; --green:{GREEN};
    --hi-text:#9fe3bd; --track:#17171b; --stagger:0.28s; --grow:0.95s;
  }}
  * {{ box-sizing:border-box; }}
  html,body {{ margin:0; background:var(--bg); }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
          color:var(--text); -webkit-font-smoothing:antialiased; }}
  .wrap {{ max-width:940px; margin:0 auto; padding:34px 30px 26px; }}
  .head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }}
  h1 {{ font-size:22px; font-weight:800; margin:0 0 22px; letter-spacing:.2px; }}
  .replay {{ flex:0 0 auto; background:#1c1c22; color:var(--text); border:1px solid #33333a;
             border-radius:8px; padding:8px 14px; font-size:13px; font-weight:600; cursor:pointer;
             transition:background .15s,border-color .15s; }}
  .replay:hover {{ background:#26262e; border-color:var(--green); }}
  .rows {{ display:flex; flex-direction:column; gap:16px; }}
  .row {{ display:grid; grid-template-columns:300px 1fr 64px; align-items:center; gap:16px;
          opacity:0; transform:translateY(6px); }}
  .row.animate {{ animation:reveal .5s ease-out forwards; animation-delay:calc(var(--i)*var(--stagger)); }}
  @keyframes reveal {{ to {{ opacity:1; transform:translateY(0); }} }}
  .label {{ display:flex; align-items:center; gap:12px; min-width:0; }}
  .logo {{ flex:0 0 30px; width:30px; height:30px; display:flex; align-items:center; justify-content:center; }}
  .logo img {{ max-width:30px; max-height:30px; object-fit:contain; }}
  .nm {{ font-size:15px; font-weight:700; line-height:1.15; }}
  .row.hi .nm {{ color:var(--hi-text); }}
  .eng {{ font-size:.62em; color:var(--sub); font-weight:700; margin-left:2px; vertical-align:super; }}
  .sub {{ display:block; font-size:11px; color:var(--sub); font-weight:500; margin-top:2px; }}
  .track {{ position:relative; height:26px; background:var(--track); border-radius:6px; overflow:hidden; }}
  .bar {{ position:absolute; left:0; top:0; bottom:0; width:0; background:var(--bar); border-radius:6px; }}
  .row.hi .bar {{ background:var(--green); box-shadow:0 0 18px rgba(31,157,87,.45); }}
  .row.animate .bar {{ width:var(--pct);
      transition:width var(--grow) cubic-bezier(.22,.61,.36,1);
      transition-delay:calc(var(--i)*var(--stagger)); }}
  .val {{ font-size:15px; font-weight:800; text-align:left; font-variant-numeric:tabular-nums;
          opacity:0; }}
  .row.animate .val {{ animation:fadeval .4s ease forwards;
      animation-delay:calc(var(--i)*var(--stagger) + .15s); }}
  @keyframes fadeval {{ to {{ opacity:1; }} }}
  .cap {{ margin-top:26px; color:var(--sub); font-size:12.5px; line-height:1.7; }}
</style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <h1>BiomniBench-DA — dual-judge mean rubric score</h1>
      <button class="replay" id="replay">↻ Replay</button>
    </div>
    <div class="rows" id="rows">{rows_joined}
    </div>
    <div class="cap">
      50 tasks · mean of two judges (DeepSeek v4-pro + Gemini 3.1 Pro) · all backends deepseek-v4-pro<br>
      {ENGINE_LEGEND}
    </div>
  </div>
<script>
  const N = {n_rows};
  const GROW_MS = 950, STAG_MS = 280;
  const rows = Array.from(document.querySelectorAll('.row'));
  function countUp(el, target, dur, delay) {{
    setTimeout(() => {{
      const t0 = performance.now();
      function tick(now) {{
        const p = Math.min(1, (now - t0) / dur);
        const e = 1 - Math.pow(1 - p, 3);            // ease-out cubic
        el.textContent = (target * e).toFixed(3);
        if (p < 1) requestAnimationFrame(tick);
        else el.textContent = target.toFixed(3);
      }}
      requestAnimationFrame(tick);
    }}, delay);
  }}
  function play() {{
    rows.forEach(r => {{ r.classList.remove('animate'); const v = r.querySelector('.val'); v.textContent = '0.000'; }});
    void document.body.offsetWidth;                   // force reflow to restart CSS anims
    rows.forEach((r, i) => {{
      r.classList.add('animate');
      const v = r.querySelector('.val');
      countUp(v, parseFloat(v.dataset.v), GROW_MS, i * STAG_MS);
    }});
  }}
  document.getElementById('replay').addEventListener('click', play);
  window.addEventListener('load', () => setTimeout(play, 250));
</script>
</body>
</html>"""


def main():
    OUT.write_text(build(), encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    print(f"-> {OUT}  ({kb:.0f} KB, self-contained)")


if __name__ == "__main__":
    main()
