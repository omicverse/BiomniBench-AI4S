#!/usr/bin/env python
"""Aggregate the published trajectories into the leaderboard.

Reads `trajectories/<backend>/<task>/grade.json` (the curated, published subset)
and writes `reports/final/matrix.csv` + `reports/final/leaderboard.md`. Then run
`scripts/plot_leaderboard.py` to render the charts from the CSV.

This is the reproducible aggregator for the published set: one authoritative
run per backend per task. (Internal multi-run provenance is not shipped.)
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAJ = ROOT / "trajectories"
OUT = ROOT / "reports" / "final"
PASS = 0.70

ORDER = ["omicos", "claude_csswitch", "evoscientist", "openscience_synsci",
         "biomni", "openscience_ai4s", "wisp"]


def main():
    rows = []
    by = defaultdict(list)
    for gj in sorted(TRAJ.glob("*/*/grade.json")):
        backend, task = gj.parent.parent.name, gj.parent.name
        try:
            g = json.load(open(gj))
        except Exception:
            continue
        score = float(g.get("score", 0.0))
        status = g.get("status", "")
        rows.append((backend, task, score, status,
                     g.get("grade_mode", ""), g.get("correct")))
        if status != "unavailable":
            by[backend].append(score)

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "matrix.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["backend", "task", "score", "status", "grade_mode", "correct"])
        for r in sorted(rows):
            w.writerow([r[0], r[1], f"{r[2]:.4f}", r[3], r[4], r[5]])

    def stats(b):
        ss = by.get(b, [])
        n = len(ss)
        if not n:
            return 0, 0.0, 0, 0.0
        p = sum(1 for s in ss if s >= PASS)
        return n, sum(ss) / n, p, 100.0 * p / n

    ranked = sorted([b for b in by], key=lambda b: -stats(b)[1])
    lines = ["# BiomniBench-AI4S — cross-agent leaderboard\n",
             "Same BiomniBench-DA tasks, same DeepSeek v4-pro rubric judge, "
             "all backends on deepseek-v4-pro.\n",
             f"Pass = score ≥ {PASS:.2f}.\n",
             "| backend | n | mean | pass@0.7 | accuracy |",
             "|---|---:|---:|---:|---:|"]
    for b in ranked:
        n, mean, p, acc = stats(b)
        lines.append(f"| `{b}` | {n} | {mean:.3f} | {p} | {acc:.1f}% |")
    (OUT / "leaderboard.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\n-> {OUT/'matrix.csv'}\n-> {OUT/'leaderboard.md'}")


if __name__ == "__main__":
    main()
