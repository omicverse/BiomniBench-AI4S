"""synthetic-sciences/openscience backend — driven headlessly via its CLI.

The product presents as a browser workspace, but the `@synsci/openscience` CLI
has a documented headless path: `openscience run --format json` streams
line-delimited JSON events and drives the same agent core (`research` primary
agent + biology/physics/ml specialists) the UI uses.

We run the published self-contained binary inside the Apptainer container (the
release binary needs glibc >= 2.18; el7 nodes have 2.17), with the omicdev
Python stack on PATH for analysis. Model parity: synsci's built-in deepseek
provider (Vercel AI SDK) exposes `deepseek/deepseek-v4-pro` via `DEEPSEEK_API_KEY`.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from .base import AdapterUnavailable, RunResult

_REPO = Path(__file__).resolve().parents[3]
_LAUNCHER = _REPO / "scripts" / "synsci-run.sh"


class OpenScienceSynsciAdapter:
    id = "openscience_synsci"
    kind = "synsci"

    def __init__(self, spec: dict):
        self.spec = spec
        self.model = dict(spec.get("model") or {})
        self._runnable: bool | None = None

    def _model_str(self) -> str:
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
                self._runnable = p.returncode == 0
            except Exception:
                self._runnable = False
        return self._runnable

    def run(self, *, instruction: str, workspace: Path, cell_dir: Path,
            model: dict) -> RunResult:
        if not self.available():
            raise AdapterUnavailable(
                "synsci openscience binary not runnable (need Apptainer "
                "container + published binary; see docs/running-competitors.md)."
            )
        from ..prompts import build_prompt

        prompt = build_prompt(instruction, flavor="generic")
        prompt_file = cell_dir / "_prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")
        traj = cell_dir / "trajectory.jsonl"
        log = cell_dir / "synsci.log"
        agent = self.model.get("agent", "research")
        timeout_s = float(self.model.get("timeout_s", 5400))

        started = time.monotonic()
        error: str | None = None
        try:
            with log.open("w", encoding="utf-8") as lf:
                p = subprocess.run(
                    ["bash", str(_LAUNCHER), "run", str(workspace),
                     self._model_str(), str(prompt_file), agent],
                    stdout=subprocess.PIPE, stderr=lf, text=True, timeout=timeout_s,
                )
            traj.write_text(p.stdout or "", encoding="utf-8")
            if p.returncode != 0:
                error = f"openscience exited {p.returncode} (see {log.name})"
        except subprocess.TimeoutExpired as e:
            error = f"openscience timed out after {timeout_s:.0f}s"
            if e.stdout:
                traj.write_text(
                    e.stdout if isinstance(e.stdout, str)
                    else e.stdout.decode("utf-8", "replace"), encoding="utf-8")
        except Exception as e:  # pragma: no cover — defensive
            error = f"{type(e).__name__}: {e}"

        counts = _parse_synsci_json(traj)
        return RunResult(
            final_text=counts.get("final_text", ""),
            tool_calls=counts.get("tool_calls", 0),
            events=counts.get("events", 0),
            input_tokens=counts.get("input_tokens", 0),
            output_tokens=counts.get("output_tokens", 0),
            error=error, elapsed_s=time.monotonic() - started,
        )


def _parse_synsci_json(path: Path) -> dict:
    """Tally synsci's line-delimited JSON events (type/tool_use/step_finish).
    Its schema is stable enough to read token usage + tool calls precisely."""
    out = {"events": 0, "tool_calls": 0, "input_tokens": 0,
           "output_tokens": 0, "final_text": ""}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        out["events"] += 1
        t = obj.get("type")
        if t == "tool_use":
            out["tool_calls"] += 1
        elif t == "text":
            txt = (obj.get("part") or {}).get("text")
            if txt:
                out["final_text"] = str(txt)[:4000]
        elif t == "step_finish":
            tok = (obj.get("part") or {}).get("tokens") or {}
            if isinstance(tok, dict):
                out["input_tokens"] += int(tok.get("input") or 0)
                out["output_tokens"] += int(tok.get("output") or 0)
    return out
