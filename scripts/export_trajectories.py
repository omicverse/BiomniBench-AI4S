#!/usr/bin/env python
"""Curate the publishable trajectory subset for HuggingFace.

From raw per-cell run outputs it copies ONLY the files safe/useful to publish:

    trajectories/<backend>/<task>/
        trace.md        # the agent's analytical trace (deliverable)
        answer.txt      # the agent's final answer (deliverable)
        grade.json      # score + status + grader_notes + criteria (kept, per
                        # decision) — but see FILTERING below
        trajectory.jsonl # optional (--with-trajectory), the raw event stream

It deliberately does NOT copy:
    * instruction.md / the task rubric  (BiomniBench-DA dataset content)
    * workspace/**                      (staged inputs + intermediate artifacts)

Usage (edit SOURCES to your run layout, or pass --runs-root + --source):
    python export_trajectories.py --runs-root /path/to/runs \
        --source omicos=omicos-clean --source claude_csswitch=final-fill ...

Raw cell layout expected:
    <runs-root>/<run-id>/<backend>/<task>/grade.json
    <runs-root>/<run-id>/<backend>/<task>/workspace/{trace.md,answer.txt}

!!! FILTERING — DO A REVIEW PASS BEFORE UPLOAD !!!
trace.md / trajectory.jsonl are model-generated and may echo the task
instruction verbatim, quote the rubric, or contain local absolute paths. Run
your own filter over trajectories/ (strip instruction echoes, scrub paths/keys)
before pushing to a public dataset. This script does the structural curation
only; it does not sanitize free text.
"""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Default authoritative run per backend (edit to match your runs). Each backend
# is published from ONE run so the leaderboard is reproducible from the set.
SOURCES = {
    "omicos":             "omicos-clean",
    "claude_csswitch":    "final-fill",
    "evoscientist":       "final-fill",
    "openscience_synsci": "final-fill",
    "openscience_ai4s":   "final-fill",
    "biomni":             "biomni-traj",
    "wisp":               "full",
}

KEEP = ("trace.md", "answer.txt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-root", required=True, type=Path)
    ap.add_argument("--source", action="append", default=[],
                    help="backend=run_id (overrides SOURCES)")
    ap.add_argument("--out", type=Path, default=ROOT / "trajectories")
    ap.add_argument("--with-trajectory", action="store_true",
                    help="also copy trajectory.jsonl (large)")
    args = ap.parse_args()

    sources = dict(SOURCES)
    for s in args.source:
        b, rid = s.split("=", 1)
        sources[b] = rid

    total = 0
    for backend, run_id in sources.items():
        base = args.runs_root / run_id / backend
        if not base.is_dir():
            print(f"skip {backend}: {base} missing")
            continue
        n = 0
        for cell in sorted(base.glob("*/")):
            task = cell.name
            grade = cell / "grade.json"
            if not grade.is_file():
                continue
            dst = args.out / backend / task
            dst.mkdir(parents=True, exist_ok=True)
            # grade.json (kept as-is: score + grader_notes + criteria)
            shutil.copy2(grade, dst / "grade.json")
            # deliverables from workspace/
            ws = cell / "workspace"
            for name in KEEP:
                src = ws / name
                if src.is_file():
                    shutil.copy2(src, dst / name)
            if args.with_trajectory and (cell / "trajectory.jsonl").is_file():
                shutil.copy2(cell / "trajectory.jsonl", dst / "trajectory.jsonl")
            n += 1
        print(f"{backend:22} {run_id:16} -> {n} cells")
        total += n

    print(f"\nexported {total} cells to {args.out}")
    print("!!! run a text-filtering pass before uploading (see module docstring) !!!")


if __name__ == "__main__":
    main()
