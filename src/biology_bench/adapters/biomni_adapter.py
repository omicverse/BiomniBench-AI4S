"""Biomni backend — snap-stanford/biomni A1 agent (the reference agent the
BiomniBench tasks originate from).

Biomni lives in its own conda env (`biomni_base`, biomni 0.0.8) with a langgraph
stack that would clash with the harness's omicdev interpreter, so we drive it
out-of-process: spawn `biomni_base/python scripts/biomni_run.py <workspace>
<prompt> <cell_dir>`. The driver instantiates A1 with the DeepSeek v4-pro
OpenAI-compatible endpoint (parity with every other backend), runs `agent.go`,
and guarantees `trace.md`+`answer.txt` land in the workspace for the shared
grader. Uses the neutral `generic` prompt flavor (no omicos `call_agent` refs).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from .base import AdapterUnavailable, RunResult

_REPO = Path(__file__).resolve().parents[3]
_DRIVER = _REPO / "scripts" / "biomni_run.py"
_DEFAULT_BIOMNI_PY = "/path/to/env/biomni_base/bin/python"


class BiomniAdapter:
    id = "biomni"
    kind = "biomni"

    def __init__(self, spec: dict):
        self.spec = spec
        self.model = dict(spec.get("model") or {})
        self._py = os.environ.get("BIOMNI_PYTHON", _DEFAULT_BIOMNI_PY)

    def available(self) -> bool:
        if not (Path(self._py).is_file() and _DRIVER.is_file()):
            return False
        # Confirm biomni actually imports in that env (cached one-shot probe).
        try:
            p = subprocess.run(
                [self._py, "-c", "import biomni"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120,
            )
            return p.returncode == 0
        except Exception:
            return False

    def run(
        self, *, instruction: str, workspace: Path, cell_dir: Path, model: dict,
    ) -> RunResult:
        if not self.available():
            raise AdapterUnavailable(
                f"biomni not runnable: {self._py} / {_DRIVER}"
            )

        from ..prompts import build_prompt

        model_cfg = {**self.model, **(model or {})}
        prompt = build_prompt(instruction, flavor="generic")
        prompt_file = cell_dir / "_prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")
        timeout_s = float(model_cfg.get("timeout_s", 5400))

        env = {**os.environ}
        env["BIOMNI_MODEL"] = model_cfg.get("model", "deepseek-v4-pro")
        env["BIOMNI_TIMEOUT"] = str(int(timeout_s))

        log = cell_dir / "biomni.log"
        started = time.monotonic()
        error: str | None = None
        summary: dict = {}
        try:
            with log.open("w", encoding="utf-8") as lf:
                proc = subprocess.run(
                    [self._py, str(_DRIVER), str(workspace),
                     str(prompt_file), str(cell_dir)],
                    cwd=str(workspace), env=env,
                    stdout=subprocess.PIPE, stderr=lf, text=True,
                    timeout=timeout_s,
                )
            out = (proc.stdout or "").strip().splitlines()
            # Last stdout line is the driver's JSON summary.
            for line in reversed(out):
                try:
                    summary = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
            if proc.returncode != 0:
                error = f"biomni driver exited {proc.returncode} (see {log.name})"
            elif summary.get("error"):
                error = summary["error"]
        except subprocess.TimeoutExpired:
            error = f"biomni timed out after {timeout_s:.0f}s"
        except Exception as e:  # pragma: no cover — defensive
            error = f"{type(e).__name__}: {e}"

        return RunResult(
            final_text="",
            final_answer="",       # graded from answer.txt on disk
            tool_calls=int(summary.get("steps", 0)),
            events=int(summary.get("steps", 0)),
            error=error,
            elapsed_s=time.monotonic() - started,
        )
