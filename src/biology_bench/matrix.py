"""(backend × task) orchestrator + leaderboard writer.

Per cell we:
  1. Stage a fresh workspace from the task's `environment/` (shared loader).
  2. Drive the backend's adapter over it (it writes `trace.md`+`answer.txt`),
     OR import a manually-produced artifact for desktop backends.
  3. Grade `trace.md`+`answer.txt` with the SHARED omicos-biomnibench rubric
     judge — identical across every backend.
  4. Persist per-cell artifacts under runs/<run_id>/<backend_id>/<task_id>/.

The report is a backend leaderboard (mean score / pass rate) plus a per-task
score grid so you can see which agent wins which task.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import _biomni
from .adapters import AdapterUnavailable, build_adapter
from .adapters.desktop_stub import DesktopStubAdapter

ob_dataset = _biomni.ob_dataset
ob_grader = _biomni.ob_grader

_PASS = 0.7  # BiomniBench rubric-pass cutoff (score >= 0.70)


@dataclass
class CellResult:
    run_id: str
    backend_id: str
    task_id: str
    paper: str
    status: str            # ok | unavailable | serve_failed | no_output
    correct: bool
    score: float
    grade_mode: str
    final_answer: str
    grader_notes: str
    criteria: dict = field(default_factory=dict)
    error: str | None = None
    elapsed_s: float = 0.0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


_log_lock = threading.Lock()


def _emit(msg: str) -> None:
    with _log_lock:
        print(msg, flush=True)


def _run_cell(
    *, run_id: str, run_root: Path, backend_spec: dict,
    task, judge_cfg: dict, import_only: bool,
) -> CellResult:
    backend_id = backend_spec["id"]
    adapter = build_adapter(backend_spec)
    cell_dir = run_root / backend_id / task.task_id
    cell_dir.mkdir(parents=True, exist_ok=True)
    workspace = ob_dataset.stage_task(task, cell_dir)

    status = "ok"
    error: str | None = None
    res = None
    started = time.monotonic()

    try:
        if import_only or backend_spec.get("kind") == "desktop":
            staged = DesktopStubAdapter.import_artifact(cell_dir, workspace)
            if not staged:
                status = "unavailable"
                error = "no manual/{trace.md,answer.txt} to import"
        elif not adapter.available():
            status = "unavailable"
            error = f"{backend_id} adapter not available in this environment"
        else:
            res = adapter.run(
                instruction=task.instruction,
                workspace=workspace,
                cell_dir=cell_dir,
                model=backend_spec.get("model") or {},
            )
            error = res.error
    except AdapterUnavailable as e:
        status = "unavailable"
        error = str(e)
    except Exception as e:  # pragma: no cover — defensive
        status = "serve_failed"
        error = f"{type(e).__name__}: {e}"

    elapsed = res.elapsed_s if res else (time.monotonic() - started)

    # Path fallback: a delegated subagent (call_agent) sometimes writes the
    # deliverables to `workspace/outputs/` instead of the workspace root, and
    # the grader only reads the root — a finished analysis would otherwise be
    # scored 0 on a path technicality. Promote them if the root is empty.
    for _name in ("trace.md", "answer.txt"):
        _root = workspace / _name
        _nested = workspace / "outputs" / _name
        if (not _root.is_file()) and _nested.is_file():
            _root.write_bytes(_nested.read_bytes())

    # Grade whatever landed in the workspace. The grader itself returns a
    # no_output verdict if neither file exists, so we always get a numeric row.
    answer_path = workspace / "answer.txt"
    final_answer = (
        answer_path.read_text(encoding="utf-8").strip()
        if answer_path.is_file() else ""
    )
    if status == "unavailable":
        cell = CellResult(
            run_id=run_id, backend_id=backend_id, task_id=task.task_id,
            paper=task.paper, status=status, correct=False, score=0.0,
            grade_mode="unavailable", final_answer="", grader_notes=error or "",
            error=error, elapsed_s=elapsed,
        )
    else:
        grade = ob_grader.grade(
            rubric=task.rubric, workspace=workspace, judge_cfg=judge_cfg
        )
        if grade.mode == "no_output" and status == "ok":
            status = "no_output"
        cell = CellResult(
            run_id=run_id, backend_id=backend_id, task_id=task.task_id,
            paper=task.paper, status=status, correct=grade.correct,
            score=grade.score, grade_mode=grade.mode,
            final_answer=final_answer or (res.final_answer if res else ""),
            grader_notes=grade.notes, criteria=grade.criteria, error=error,
            elapsed_s=elapsed,
            tool_calls=res.tool_calls if res else 0,
            input_tokens=res.input_tokens if res else 0,
            output_tokens=res.output_tokens if res else 0,
        )

    (cell_dir / "grade.json").write_text(
        json.dumps(asdict(cell), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return cell


def run_matrix(
    *, project_root: Path, run_id: str, backends: list[dict], tasks: list,
    judge_cfg: dict, concurrency: int = 1, import_only: bool = False,
) -> list[CellResult]:
    run_root = project_root / "runs" / run_id
    run_root.mkdir(parents=True, exist_ok=True)

    cells = [(b, t) for b in backends for t in tasks]
    _emit(
        f"[matrix] {len(cells)} cell(s): {len(backends)} backend(s) × "
        f"{len(tasks)} task(s), concurrency={concurrency}"
    )
    results: list[CellResult] = [None] * len(cells)  # type: ignore[list-item]

    def _do(i, b, t):
        return i, _run_cell(
            run_id=run_id, run_root=run_root, backend_spec=b, task=t,
            judge_cfg=judge_cfg, import_only=import_only,
        )

    if concurrency <= 1:
        for i, (b, t) in enumerate(cells):
            _, results[i] = _do(i, b, t)
            r = results[i]
            _emit(f"[matrix] {i+1}/{len(cells)} {r.backend_id}/{r.task_id} "
                  f"status={r.status} score={r.score:.2f} elapsed={r.elapsed_s:.0f}s")
    else:
        done = 0
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = {pool.submit(_do, i, b, t): (i, b, t)
                    for i, (b, t) in enumerate(cells)}
            for fut in as_completed(futs):
                i, r = fut.result()
                results[i] = r
                done += 1
                _emit(f"[matrix] {done}/{len(cells)} {r.backend_id}/{r.task_id} "
                      f"status={r.status} score={r.score:.2f} "
                      f"elapsed={r.elapsed_s:.0f}s")
    return [r for r in results if r is not None]


def write_report(project_root: Path, run_id: str,
                 results: list[CellResult]) -> Path:
    """Write reports/<run_id>/matrix.csv + leaderboard.md."""

    import csv

    rep = project_root / "reports" / run_id
    rep.mkdir(parents=True, exist_ok=True)

    fields = [k for k in CellResult.__dataclass_fields__ if k != "criteria"]
    with (rep / "matrix.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow({k: getattr(r, k) for k in fields})

    by_backend: dict[str, list[CellResult]] = {}
    for r in results:
        by_backend.setdefault(r.backend_id, []).append(r)
    task_ids = sorted({r.task_id for r in results})

    lines = [f"# biology_bench — cross-agent leaderboard `{run_id}`\n"]
    lines.append("Same BiomniBench-DA tasks, same rubric judge "
                 "(DeepSeek v4-pro), across every backend. "
                 f"Pass = score ≥ {_PASS:.2f}.\n")
    lines.append("| backend | ran | answered | passed | accuracy | mean score |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    # Rank by mean score over cells that actually ran.
    def _mean(rs):
        ran = [r for r in rs if r.status not in ("unavailable",)]
        return sum(r.score for r in ran) / len(ran) if ran else 0.0
    for backend_id, rs in sorted(by_backend.items(), key=lambda kv: -_mean(kv[1])):
        ran = [r for r in rs if r.status != "unavailable"]
        answered = [r for r in ran if r.final_answer or r.grade_mode not in
                    ("no_output", "unavailable")]
        passed = sum(1 for r in ran if r.correct)
        acc = passed / len(ran) if ran else 0.0
        lines.append(
            f"| `{backend_id}` | {len(ran)}/{len(rs)} | {len(answered)} | "
            f"{passed} | {acc:.1%} | {_mean(rs):.3f} |"
        )

    # Per-task score grid (backend columns).
    backends = sorted(by_backend)
    lines.append("\n## Per-task scores\n")
    lines.append("| task | " + " | ".join(f"`{b}`" for b in backends) + " |")
    lines.append("|---" * (len(backends) + 1) + "|")
    score_at = {(r.backend_id, r.task_id): r for r in results}
    for tid in task_ids:
        cells = []
        for b in backends:
            r = score_at.get((b, tid))
            cells.append("—" if r is None or r.status == "unavailable"
                         else f"{r.score:.2f}")
        lines.append(f"| `{tid}` | " + " | ".join(cells) + " |")

    (rep / "leaderboard.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rep
