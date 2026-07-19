"""biology-bench command line.

    biology-bench fetch                         # download BiomniBench-DA (via biomni loader)
    biology-bench smoke [--task da-4-1] [--backends omicos,evoscientist]
    biology-bench run   [--tasks ...] [--backends ...] [--concurrency N] [--run-id ID]
    biology-bench report <run_id>               # regenerate CSV + leaderboard from grade.json
    biology-bench import-artifacts --run-id ID [--backends ...] [--tasks ...]
                                                # grade desktop-produced manual/ artifacts

Backends and the judge come from configs/. Every backend runs the same tasks
and is scored by the same rubric judge, so the leaderboard is apples-to-apples.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

from . import _biomni, matrix

_ROOT = Path(__file__).resolve().parents[2]  # biology_bench/
ob_dataset = _biomni.ob_dataset


def _load_yaml(p: Path) -> dict:
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _backends(names: str | None) -> list[dict]:
    cfg = _load_yaml(_ROOT / "configs" / "backends.yaml").get("backends", [])
    if names:
        wanted = [n.strip() for n in names.split(",") if n.strip()]
        by_id = {b["id"]: b for b in cfg}
        missing = [n for n in wanted if n not in by_id]
        if missing:
            sys.exit(f"unknown backend(s): {missing}. "
                     f"Known: {sorted(by_id)}")
        return [by_id[n] for n in wanted]
    return [b for b in cfg if b.get("enabled", True)]


def _judge_cfg() -> dict:
    return _load_yaml(_ROOT / "configs" / "models.yaml").get("judge_model", {})


def _tasks(ids: list[str] | None):
    tasks = ob_dataset.load_tasks(task_ids=ids)
    if not tasks:
        sys.exit("no tasks loaded — run `biology-bench fetch` first "
                 "(and ensure HF_TOKEN is set for the gated dataset).")
    return tasks


def _default_run_id(prefix: str) -> str:
    return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}"


def _finish(run_id: str, results) -> None:
    rep = matrix.write_report(_ROOT, run_id, results)
    ran = [r for r in results if r.status != "unavailable"]
    passed = sum(1 for r in ran if r.correct)
    print(f"\n[biology-bench] run={run_id}: {len(results)} cell(s), "
          f"{len(ran)} ran, {passed} passed")
    print(f"[biology-bench] report -> {rep/'leaderboard.md'}")


def cmd_fetch(_args) -> None:
    ob_dataset.fetch_all()
    print("[biology-bench] dataset ready.")


def cmd_smoke(args) -> None:
    backends = _backends(args.backends or "omicos,evoscientist")
    tasks = _tasks([args.task])
    run_id = args.run_id or _default_run_id("smoke")
    results = matrix.run_matrix(
        project_root=_ROOT, run_id=run_id, backends=backends, tasks=tasks,
        judge_cfg=_judge_cfg(), concurrency=1,
    )
    _finish(run_id, results)


def cmd_run(args) -> None:
    backends = _backends(args.backends)
    ids = [t.strip() for t in args.tasks.split(",")] if args.tasks else None
    tasks = _tasks(ids)
    run_id = args.run_id or _default_run_id("run")
    results = matrix.run_matrix(
        project_root=_ROOT, run_id=run_id, backends=backends, tasks=tasks,
        judge_cfg=_judge_cfg(), concurrency=args.concurrency,
    )
    _finish(run_id, results)


def cmd_import(args) -> None:
    backends = _backends(args.backends)
    ids = [t.strip() for t in args.tasks.split(",")] if args.tasks else None
    tasks = _tasks(ids)
    results = matrix.run_matrix(
        project_root=_ROOT, run_id=args.run_id, backends=backends, tasks=tasks,
        judge_cfg=_judge_cfg(), concurrency=1, import_only=True,
    )
    _finish(args.run_id, results)


def cmd_report(args) -> None:
    run_root = _ROOT / "runs" / args.run_id
    if not run_root.is_dir():
        sys.exit(f"no run dir at {run_root}")
    results = []
    for grade_file in run_root.glob("*/*/grade.json"):
        data = json.loads(grade_file.read_text(encoding="utf-8"))
        results.append(matrix.CellResult(**data))
    if not results:
        sys.exit(f"no grade.json under {run_root}")
    _finish(args.run_id, results)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="biology-bench")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("fetch").set_defaults(fn=cmd_fetch)

    s = sub.add_parser("smoke")
    s.add_argument("--task", default="da-4-1")
    s.add_argument("--backends", default=None)
    s.add_argument("--run-id", default=None)
    s.set_defaults(fn=cmd_smoke)

    r = sub.add_parser("run")
    r.add_argument("--tasks", default=None, help="comma-separated task ids")
    r.add_argument("--backends", default=None)
    r.add_argument("--concurrency", type=int, default=1)
    r.add_argument("--run-id", default=None)
    r.set_defaults(fn=cmd_run)

    i = sub.add_parser("import-artifacts")
    i.add_argument("--run-id", required=True)
    i.add_argument("--backends", default=None)
    i.add_argument("--tasks", default=None)
    i.set_defaults(fn=cmd_import)

    rp = sub.add_parser("report")
    rp.add_argument("run_id")
    rp.set_defaults(fn=cmd_report)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
