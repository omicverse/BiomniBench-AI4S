"""EvoScientist backend (https://github.com/EvoScientist/EvoScientist).

EvoScientist ships a headless CLI, `EvoSci`, with a single-shot mode:

    EvoSci -p "<prompt>" --workdir <dir> --auto-approve --dangerous \
           --output-format stream-json

We drive that: run in the staged workspace, tell it (via the shared OUTPUT
CONTRACT prompt) to write `trace.md`+`answer.txt` there, and tee its
line-delimited JSON events to `trajectory.jsonl`. Token/tool counters are
parsed best-effort — EvoScientist's event schema is not contractual, so unknown
counters stay 0 rather than guessing.

If `EvoSci` is not on PATH the adapter reports unavailable and the leaderboard
shows this backend as skipped (see docs/parity-caveats.md for install notes).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .base import AdapterUnavailable, RunResult

# EvoSci's own flags that never change. Model/provider selection is via env
# (ANTHROPIC_API_KEY etc.) or the backend's `model` block -> extra_args.
# `--mode run` = isolated per-session (no shared daemon). REQUIRED for
# concurrency: the default `--mode daemon` shares one langgraph dev server
# (port 6174) + sessions.db + a single workspace lock, so parallel EvoSci
# processes collide ("Stop the other EvoSci session") and all but one exit 1.
#
# `--mode run` CANNOT be combined with `--workdir`/`--use-cwd` (EvoSci exits 2).
# Instead it materializes an isolated run directory `<cwd>/runs/<name>/` and
# operates there. We run with cwd=workspace and pin `--name` so the run dir is
# the deterministic `<workspace>/runs/<_RUN_NAME>/`; `--dangerous` gives real-FS
# access so the agent can still reach the staged data files. After the run we
# promote `runs/<_RUN_NAME>/{trace.md,answer.txt}` up to the workspace root,
# where the shared grader looks.
_RUN_NAME = "bench"
_BASE_ARGS = ["--mode", "run", "--name", _RUN_NAME, "--auto-approve",
              "--dangerous", "--output-format", "stream-json"]


class EvoScientistAdapter:
    id = "evoscientist"
    kind = "evoscientist"

    def __init__(self, spec: dict):
        self.spec = spec
        self.model = dict(spec.get("model") or {})
        # EVOSCI_BIN lets an operator point at a wrapper (e.g. the Apptainer
        # launcher, scripts/evosci-apptainer.sh) that supplies a newer glibc.
        self._explicit_bin = bool(os.environ.get("EVOSCI_BIN"))
        self._bin = os.environ.get("EVOSCI_BIN") or shutil.which("EvoSci")
        self._runnable: bool | None = None

    def available(self) -> bool:
        """True only if `EvoSci` is on PATH AND actually runnable here.

        `EvoSci --version` is a false positive on el7 (it prints before the
        code-interpreter middleware loads). The real blocker is that
        EvoScientist's tool sandbox (quickjs_rs -> wasmtime) dlopens a native
        lib needing GLIBC_2.18, while Sherlock's el7 nodes ship 2.17. So we
        probe `import wasmtime` in EvoScientist's own venv python — the exact
        import that crashes the agent loop — and cache it. A clean
        "unavailable" row beats a traceback in a graded cell. See
        docs/parity-caveats.md §2b for the Apptainer remediation.
        """

        if not self._bin:
            return False
        if self._runnable is None:
            self._runnable = self._probe_runnable()
        return self._runnable

    def _probe_runnable(self) -> bool:
        # Custom wrapper (EVOSCI_BIN): probe wasmtime THROUGH it — the launcher's
        # `--probe-wasmtime` runs the import inside whatever runtime it provides
        # (e.g. the Apptainer container's newer glibc).
        if self._explicit_bin:
            try:
                p = subprocess.run(
                    [self._bin, "--probe-wasmtime"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=180,
                )
                return p.returncode == 0
            except Exception:
                return False
        # Default PATH install: probe the host venv python directly. On el7 this
        # correctly returns False (GLIBC_2.18 wall).
        venv_py = Path(os.path.realpath(self._bin)).parent / "python"
        if not venv_py.exists():
            return True  # can't locate venv python — assume runnable, let run() surface errors
        try:
            p = subprocess.run(
                [str(venv_py), "-c", "import wasmtime"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=60,
            )
            return p.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _free_port() -> int:
        """Grab an ephemeral free TCP port (closed immediately; small TOCTOU
        window is fine across distinct high ports)."""
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        return p

    @staticmethod
    def _home_env(cell_dir: Path) -> dict:
        """Per-cell isolation so concurrent EvoSci processes don't collide.

        EvoSci always starts a langgraph dev server on a SINGLE port
        (`langgraph_dev_port`, default 6174) bound to one workspace — even under
        `--mode run`. Concurrent cells therefore all fight over 6174 and every
        one but the first dies instantly ("already running for workspace …").
        Fix: give each cell (a) a unique free port via
        EVOSCIENTIST_LANGGRAPH_DEV_PORT / _WEBUI_PORT, and (b) its own
        EVOSCIENTIST_HOME (isolated sessions.db + EvoMemory, avoids SQLite lock
        contention). XDG_CONFIG_HOME stays SHARED — that's where the deepseek
        provider/key config (set once via `EvoSci config set`) lives, read-only
        during the run.
        """
        home = cell_dir / ".evoscientist"
        home.mkdir(parents=True, exist_ok=True)
        return {
            "XDG_CONFIG_HOME": os.environ.get(
                "XDG_CONFIG_HOME", "/path/to/.config"),
            "EVOSCIENTIST_HOME": str(home),
            "EVOSCIENTIST_LANGGRAPH_DEV_PORT": str(EvoScientistAdapter._free_port()),
            "EVOSCIENTIST_WEBUI_PORT": str(EvoScientistAdapter._free_port()),
        }

    def run(
        self,
        *,
        instruction: str,
        workspace: Path,
        cell_dir: Path,
        model: dict,
    ) -> RunResult:
        if not self.available():
            raise AdapterUnavailable(
                "EvoSci not on PATH. `uv tool install EvoScientist` "
                "(see docs/parity-caveats.md)."
            )

        from ..prompts import build_prompt

        model_cfg = {**self.model, **(model or {})}
        prompt = build_prompt(instruction, flavor="generic")
        extra = list(model_cfg.get("extra_args") or [])
        timeout_s = float(model_cfg.get("timeout_s", 5400))

        # No --workdir: it conflicts with --mode run. The agent runs with
        # cwd=workspace and --dangerous (real-FS), writing into
        # <workspace>/runs/<_RUN_NAME>/ which we promote afterwards.
        cmd = [
            self._bin, "-p", prompt,
            *_BASE_ARGS, *extra,
        ]
        traj = cell_dir / "trajectory.jsonl"
        log = cell_dir / "evosci.log"

        started = time.monotonic()
        error: str | None = None
        # Run inside the workspace too, so a build that ignores --workdir still
        # writes trace.md/answer.txt to the graded directory.
        try:
            with log.open("w", encoding="utf-8") as lf:
                proc = subprocess.run(
                    cmd,
                    cwd=str(workspace),
                    env={**os.environ, **self._home_env(cell_dir),
                         **_provider_env(model_cfg)},
                    stdout=subprocess.PIPE,
                    stderr=lf,
                    text=True,
                    timeout=timeout_s,
                )
            traj.write_text(proc.stdout or "", encoding="utf-8")
            if proc.returncode != 0:
                error = f"EvoSci exited {proc.returncode} (see {log.name})"
        except subprocess.TimeoutExpired as e:
            error = f"EvoSci timed out after {timeout_s:.0f}s"
            if e.stdout:
                traj.write_text(
                    e.stdout if isinstance(e.stdout, str) else e.stdout.decode(
                        "utf-8", "replace"),
                    encoding="utf-8",
                )
        except Exception as e:  # pragma: no cover — defensive
            error = f"{type(e).__name__}: {e}"

        # Promote deliverables from the isolated run dir to the workspace root
        # (the grader reads <workspace>/{trace.md,answer.txt}). --mode run wrote
        # them to <workspace>/runs/<_RUN_NAME>/; copy up if the root lacks them.
        run_dir = workspace / "runs" / _RUN_NAME
        for _name in ("trace.md", "answer.txt"):
            _root = workspace / _name
            _nested = run_dir / _name
            if (not _root.is_file()) and _nested.is_file():
                _root.write_bytes(_nested.read_bytes())

        counts = _parse_stream_json(traj)
        return RunResult(
            final_text=counts.get("final_text", ""),
            final_answer="",  # graded from answer.txt, not the stream
            tool_calls=counts.get("tool_calls", 0),
            events=counts.get("events", 0),
            input_tokens=counts.get("input_tokens", 0),
            output_tokens=counts.get("output_tokens", 0),
            error=error,
            elapsed_s=time.monotonic() - started,
        )


def _provider_env(model_cfg: dict) -> dict:
    """Map a `model` block onto env EvoScientist reads. EvoScientist is
    model-agnostic and configured via provider env vars / its own config; we
    only forward a DeepSeek OpenAI-compatible base URL when the backend asks
    for deepseek and one is present, so parity with omicos is at least
    attempted (documented in docs/parity-caveats.md)."""

    env: dict[str, str] = {}
    if (model_cfg.get("provider") or "").lower() == "deepseek":
        base = os.environ.get("DEEPSEEK_API_BASE")
        key = os.environ.get("DEEPSEEK_API_KEY")
        if base:
            env["OPENAI_BASE_URL"] = base
        if key:
            env["OPENAI_API_KEY"] = key
    return env


def _parse_stream_json(path: Path) -> dict:
    """Best-effort tally over EvoSci's line-delimited JSON. Tolerant of an
    unknown schema: counts any object per line as an event, sums common
    token-usage shapes, counts tool-call-ish events."""

    out = {"events": 0, "tool_calls": 0, "input_tokens": 0,
           "output_tokens": 0, "final_text": ""}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        out["events"] += 1
        etype = str(obj.get("type") or obj.get("event") or "").lower()
        if "tool" in etype:
            out["tool_calls"] += 1
        usage = obj.get("usage") or {}
        if isinstance(usage, dict):
            out["input_tokens"] += int(usage.get("input_tokens")
                                       or usage.get("prompt_tokens") or 0)
            out["output_tokens"] += int(usage.get("output_tokens")
                                        or usage.get("completion_tokens") or 0)
        if etype in ("result", "final", "assistant") and obj.get("text"):
            out["final_text"] = str(obj["text"])[:4000]
    return out
