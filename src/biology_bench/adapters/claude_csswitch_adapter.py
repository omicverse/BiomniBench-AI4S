"""Claude (Claude Science) on DeepSeek, via CSswitch's gateway.

Claude Science is a closed-source macOS/web app with no Linux/headless build, so
it can't be driven directly. The nearest headless equivalent — and the one
CSswitch itself is built around — is Claude's own agent CLI (Claude Code) with
its Anthropic requests routed through CSswitch's `csswitch-gateway`, which
rewrites the `claude-opus-4-8` model to `deepseek-v4-pro` and forwards to
DeepSeek's native Anthropic endpoint. So this backend runs the SAME
deepseek-v4-pro as the others, but through Claude's agent + CSswitch's router.

Everything runs inside the Apptainer container (scripts/claude-csswitch.sh):
gateway (Rust binary) + claude CLI (node) + omicdev Python kernel.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from .base import AdapterUnavailable, RunResult

_REPO = Path(__file__).resolve().parents[3]
_LAUNCHER = _REPO / "scripts" / "claude-csswitch.sh"


class ClaudeCSswitchAdapter:
    id = "claude_csswitch"
    kind = "claude_csswitch"

    def __init__(self, spec: dict):
        self.spec = spec
        self.model = dict(spec.get("model") or {})
        self._runnable: bool | None = None

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
                "claude CLI / csswitch-gateway not available (need the built "
                "gateway + claude CLI + container; see docs/running-competitors.md)."
            )
        from ..prompts import build_prompt

        prompt = build_prompt(instruction, flavor="generic")
        prompt_file = cell_dir / "_prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")
        traj = cell_dir / "trajectory.jsonl"
        log = cell_dir / "claude.log"
        timeout_s = float(self.model.get("timeout_s", 5400))

        started = time.monotonic()
        error: str | None = None
        try:
            with log.open("w", encoding="utf-8") as lf:
                p = subprocess.run(
                    ["bash", str(_LAUNCHER), "run", str(workspace), str(prompt_file)],
                    stdout=subprocess.PIPE, stderr=lf, text=True, timeout=timeout_s,
                )
            traj.write_text(p.stdout or "", encoding="utf-8")
            if p.returncode != 0:
                error = f"claude/gateway exited {p.returncode} (see {log.name})"
        except subprocess.TimeoutExpired as e:
            error = f"claude timed out after {timeout_s:.0f}s"
            if e.stdout:
                traj.write_text(
                    e.stdout if isinstance(e.stdout, str)
                    else e.stdout.decode("utf-8", "replace"), encoding="utf-8")
        except Exception as e:  # pragma: no cover — defensive
            error = f"{type(e).__name__}: {e}"

        counts = _parse_claude_stream(traj)
        return RunResult(
            final_text=counts.get("final_text", ""),
            tool_calls=counts.get("tool_calls", 0),
            events=counts.get("events", 0),
            input_tokens=counts.get("input_tokens", 0),
            output_tokens=counts.get("output_tokens", 0),
            error=error, elapsed_s=time.monotonic() - started,
        )


def _parse_claude_stream(path: Path) -> dict:
    """Tally Claude Code's stream-json output (type=assistant/tool_use/result)."""
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
        # Claude Code stream-json: assistant messages carry content blocks;
        # tool_use blocks are tool calls; result carries usage + final text.
        msg = obj.get("message") or {}
        for blk in (msg.get("content") or []):
            if isinstance(blk, dict) and blk.get("type") == "tool_use":
                out["tool_calls"] += 1
        usage = msg.get("usage") or obj.get("usage") or {}
        if isinstance(usage, dict):
            out["input_tokens"] += int(usage.get("input_tokens") or 0)
            out["output_tokens"] += int(usage.get("output_tokens") or 0)
        if obj.get("type") == "result" and obj.get("result"):
            out["final_text"] = str(obj["result"])[:4000]
    return out
