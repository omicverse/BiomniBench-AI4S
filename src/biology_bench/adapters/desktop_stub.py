"""Desktop / browser workbench backends (synsci, ai4s-research, aipoch).

These are GUI apps — an npm→browser workbench and two desktop (Tauri / notebook)
apps. None exposes a batch-drivable headless CLI, so they cannot be run on a
compute node the way omicos and EvoScientist can. The adapter therefore always
reports `available() == False` and refuses to `run()`.

They can still be scored on the SAME rubric via the *bring-your-own-artifact*
path: run the task by hand on a desktop, then drop the produced files at
`runs/<run_id>/<backend_id>/<task_id>/manual/{trace.md,answer.txt}` and call
`biology-bench import-artifacts`. `import_artifact()` below copies those into
the graded workspace. See docs/running-competitors.md.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .base import AdapterUnavailable, RunResult


class DesktopStubAdapter:
    kind = "desktop"

    def __init__(self, spec: dict):
        self.spec = spec
        self.id = spec.get("id", "desktop")
        self.repo = spec.get("repo", "")
        self.note = spec.get("note", "")

    def available(self) -> bool:
        return False

    def run(self, *, instruction, workspace, cell_dir, model) -> RunResult:
        raise AdapterUnavailable(
            f"{self.id} is a desktop/browser app ({self.note}); it cannot be "
            "driven headlessly. Produce trace.md+answer.txt on a desktop and "
            "use `biology-bench import-artifacts` (docs/running-competitors.md)."
        )

    @staticmethod
    def import_artifact(cell_dir: Path, workspace: Path) -> bool:
        """Copy a manually-produced `manual/{trace.md,answer.txt}` into the
        graded workspace. Returns True if at least one file was staged."""

        manual = cell_dir / "manual"
        staged = False
        for name in ("trace.md", "answer.txt"):
            src = manual / name
            if src.is_file():
                shutil.copy2(src, workspace / name)
                staged = True
        return staged
