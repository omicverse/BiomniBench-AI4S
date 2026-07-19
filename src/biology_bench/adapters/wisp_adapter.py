"""xuzhougeng/wisp-science backend — driven via its headless `wisp-science` CLI.

wisp ships a real headless agent binary (crate wisp-cli). It's a Rust native
binary compiled on this el7 host, so unlike the container-bound competitors it
runs DIRECTLY. The CLI is an stdin REPL that reads ONE line per turn, so the
prompt is flattened to a single line and fed via stdin + `/q` (see
scripts/wisp-run.sh). wisp wires a bundled Python + R kernel and ~230
bioinformatics MCP tools; model parity is deepseek-v4-pro through its
OpenAI-compatible provider path.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from .base import AdapterUnavailable, RunResult

_REPO = Path(__file__).resolve().parents[3]
_LAUNCHER = _REPO / "scripts" / "wisp-run.sh"


class WispAdapter:
    id = "wisp"
    kind = "wisp"

    def __init__(self, spec: dict):
        self.spec = spec
        self.model = dict(spec.get("model") or {})
        self._runnable: bool | None = None

    def _model_str(self) -> str:
        # wisp wants a bare model name (WISP_MODEL), not provider/model.
        return self.model.get("model", "deepseek-v4-pro")

    def available(self) -> bool:
        if not _LAUNCHER.is_file():
            return False
        if self._runnable is None:
            try:
                p = subprocess.run(
                    ["bash", str(_LAUNCHER), "--probe"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=30,
                )
                self._runnable = p.returncode == 0
            except Exception:
                self._runnable = False
        return self._runnable

    def run(self, *, instruction: str, workspace: Path, cell_dir: Path,
            model: dict) -> RunResult:
        if not self.available():
            raise AdapterUnavailable(
                "wisp-science binary not built (cargo build --release -p "
                "wisp-cli; see docs/running-competitors.md)."
            )
        from ..prompts import build_prompt

        # wisp's REPL reads one line per turn — flatten the (multi-line) prompt
        # to a single line so the whole task arrives as ONE turn.
        prompt = build_prompt(instruction, flavor="generic")
        prompt_1line = re.sub(r"\s*\n\s*", " ", prompt).strip()
        prompt_file = cell_dir / "_prompt.txt"
        prompt_file.write_text(prompt_1line, encoding="utf-8")
        traj = cell_dir / "trajectory.txt"
        log = cell_dir / "wisp.log"
        timeout_s = float(self.model.get("timeout_s", 5400))

        started = time.monotonic()
        error: str | None = None
        try:
            with log.open("w", encoding="utf-8") as lf:
                p = subprocess.run(
                    ["bash", str(_LAUNCHER), "run", str(workspace),
                     self._model_str(), str(prompt_file)],
                    stdout=subprocess.PIPE, stderr=lf, text=True, timeout=timeout_s,
                )
            traj.write_text(p.stdout or "", encoding="utf-8")
            if p.returncode != 0:
                error = f"wisp exited {p.returncode} (see {log.name})"
        except subprocess.TimeoutExpired as e:
            error = f"wisp timed out after {timeout_s:.0f}s"
            if e.stdout:
                traj.write_text(
                    e.stdout if isinstance(e.stdout, str)
                    else e.stdout.decode("utf-8", "replace"), encoding="utf-8")
        except Exception as e:  # pragma: no cover — defensive
            error = f"{type(e).__name__}: {e}"

        counts = _parse_wisp_output(traj)
        return RunResult(
            final_text=counts.get("final_text", ""),
            tool_calls=counts.get("tool_calls", 0),
            events=counts.get("rounds", 0),
            input_tokens=counts.get("input_tokens", 0),
            output_tokens=counts.get("output_tokens", 0),
            error=error, elapsed_s=time.monotonic() - started,
        )


# wisp prints human-readable turns, not JSON. Tally tool invocations (lines that
# start with the tool marker "›") and token usage from "round N: Xk in / Yk out".
_ROUND_RE = re.compile(r"round\s+\d+:\s+([\d.]+)k\s+in\s+/\s+([\d.]+)k\s+out")


def _parse_wisp_output(path: Path) -> dict:
    out = {"rounds": 0, "tool_calls": 0, "input_tokens": 0,
           "output_tokens": 0, "final_text": ""}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("›") or line.startswith("> "):  # tool-call marker
            out["tool_calls"] += 1
        m = _ROUND_RE.search(line)
        if m:
            out["rounds"] += 1
            out["input_tokens"] += int(float(m.group(1)) * 1000)
            out["output_tokens"] += int(float(m.group(2)) * 1000)
    return out
