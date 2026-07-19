"""ai4s-research/open-science backend — driven headlessly via its OpenCode core.

The product ships as a Tauri desktop app, but its actual agent runtime is a
bundled **OpenCode** binary that the desktop shell spawns as a sidecar
(`apps/desktop/src-tauri/src/runtime.rs`). We bypass the GUI and drive that same
binary directly with `opencode run` (single-shot, `--format json`), overlaying
the project's own product configuration so it behaves as *ai4s open-science*,
not bare OpenCode:

  * `runtime/skills/core/*`  -> `<workspace>/.opencode/skills/`  (the 13 science
    skills: reproducible-research, literature-review, publication-figures, …)
  * `runtime/harness/AGENTS.md` -> `<workspace>/AGENTS.md`  (agent instructions)

The opencode binary needs glibc >= 2.18, so it runs inside the Apptainer
container via `scripts/opencode-ai4s.sh` (same image as the EvoScientist path).
Model parity with omicos: opencode's built-in deepseek provider natively exposes
`deepseek-v4-pro`, authed through `DEEPSEEK_API_KEY`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .base import AdapterUnavailable, RunResult

_REPO = Path(__file__).resolve().parents[3]  # biology_bench/
_LAUNCHER = _REPO / "scripts" / "opencode-ai4s.sh"
_AI4S = _REPO / "vendor" / "ai4s"
_SKILLS_SRC = _AI4S / "runtime" / "skills" / "core"
_AGENTS_SRC = _AI4S / "runtime" / "harness" / "AGENTS.md"


class OpenScienceAI4SAdapter:
    id = "openscience_ai4s"
    kind = "ai4s"

    def __init__(self, spec: dict):
        self.spec = spec
        self.model = dict(spec.get("model") or {})
        self._runnable: bool | None = None

    def _model_str(self) -> str:
        # backends.yaml carries provider/model separately; opencode wants
        # "provider/model" (e.g. deepseek/deepseek-v4-pro).
        prov = self.model.get("provider", "deepseek")
        mid = self.model.get("model", "deepseek-v4-pro")
        return mid if "/" in mid else f"{prov}/{mid}"

    def available(self) -> bool:
        if not _LAUNCHER.is_file():
            return False
        if self._runnable is None:
            try:
                p = subprocess.run(
                    ["bash", str(_LAUNCHER), "--probe"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=120,
                )
                self._runnable = p.returncode == 0 and _SKILLS_SRC.is_dir()
            except Exception:
                self._runnable = False
        return self._runnable

    def _overlay_product(self, workspace: Path) -> int:
        """Drop ai4s's skills + AGENTS.md into the workspace so opencode loads
        the product config. Returns the number of skills staged."""
        skills_dst = workspace / ".opencode" / "skills"
        skills_dst.mkdir(parents=True, exist_ok=True)
        n = 0
        if _SKILLS_SRC.is_dir():
            for skill in _SKILLS_SRC.iterdir():
                if skill.is_dir():
                    shutil.copytree(skill, skills_dst / skill.name, dirs_exist_ok=True)
                    n += 1
        if _AGENTS_SRC.is_file():
            shutil.copy2(_AGENTS_SRC, workspace / "AGENTS.md")
        return n

    def run(self, *, instruction: str, workspace: Path, cell_dir: Path,
            model: dict) -> RunResult:
        if not self.available():
            raise AdapterUnavailable(
                "ai4s opencode core not runnable (need Apptainer container + "
                "opencode binary; see docs/running-competitors.md)."
            )
        from ..prompts import build_prompt

        self._overlay_product(workspace)
        prompt = build_prompt(instruction, flavor="generic")
        prompt_file = cell_dir / "_prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")
        traj = cell_dir / "trajectory.jsonl"
        log = cell_dir / "opencode.log"

        model_str = self._model_str()
        timeout_s = float(self.model.get("timeout_s", 5400))
        started = time.monotonic()
        error: str | None = None
        try:
            with log.open("w", encoding="utf-8") as lf:
                p = subprocess.run(
                    ["bash", str(_LAUNCHER), "run", str(workspace), model_str,
                     str(prompt_file)],
                    stdout=subprocess.PIPE, stderr=lf, text=True, timeout=timeout_s,
                )
            traj.write_text(p.stdout or "", encoding="utf-8")
            if p.returncode != 0:
                error = f"opencode exited {p.returncode} (see {log.name})"
        except subprocess.TimeoutExpired as e:
            error = f"opencode timed out after {timeout_s:.0f}s"
            if e.stdout:
                traj.write_text(
                    e.stdout if isinstance(e.stdout, str)
                    else e.stdout.decode("utf-8", "replace"), encoding="utf-8")
        except Exception as e:  # pragma: no cover — defensive
            error = f"{type(e).__name__}: {e}"

        counts = _parse_opencode_json(traj)
        return RunResult(
            final_text=counts.get("final_text", ""),
            tool_calls=counts.get("tool_calls", 0),
            events=counts.get("events", 0),
            input_tokens=counts.get("input_tokens", 0),
            output_tokens=counts.get("output_tokens", 0),
            error=error, elapsed_s=time.monotonic() - started,
        )


def _parse_opencode_json(path: Path) -> dict:
    """Best-effort tally over opencode's line-delimited JSON events. Schema is
    not contractual, so unknown counters stay 0."""
    out = {"events": 0, "tool_calls": 0, "input_tokens": 0,
           "output_tokens": 0, "final_text": ""}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        out["events"] += 1
        blob = json.dumps(obj).lower()
        if '"tool"' in blob or "tool_call" in blob:
            out["tool_calls"] += 1
        tok = obj.get("tokens") or {}
        if isinstance(tok, dict):
            out["input_tokens"] += int(tok.get("input") or 0)
            out["output_tokens"] += int(tok.get("output") or 0)
    return out
