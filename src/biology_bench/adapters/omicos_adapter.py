"""omicos-core backend.

Drives the `vertical_agent_selector` agent exactly like omicos-biomnibench and
`omicos-covid/slice_reg_test/_run.py`: build a flat merged agent catalog from
the omicos-admin domain tree, point the runner's overlay env vars at it, spawn
`omicos serve` against the staged workspace, and stream one turn.

Environment knobs (all overridable; defaults match the proven slice_reg_test run):
  OMICOS_BIN              -> omicos-core/target/release/omicos
  OMICOS_KERNEL_PYTHON    -> omicdev conda env (carries ov.genetics backends)
  OMICOS_ADMIN_ROOT       -> omicos-admin (for the domain agents+skills overlay)
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path

from .base import AdapterUnavailable, RunResult

_DEV_ROOT = Path(__file__).resolve().parents[4]  # .../omicos_dev
_DEFAULT_OMICOS_BIN = _DEV_ROOT / "omicos-core" / "target" / "release" / "omicos"
_DEFAULT_ADMIN_ROOT = _DEV_ROOT / "omicos-admin"
_DEFAULT_KERNEL_PY = "/path/to/env/omicdev/bin/python"
_DOMAINS = ("biology", "shared", "humanities_social")

# Max "continue, you haven't written the files yet" follow-up turns before we
# accept a no_output. Two is enough to clear a plan-approval stall or a
# skill-loading livelock without masking a genuinely stuck run.
_MAX_CONTINUE_NUDGES = 2
_CONTINUE_NUDGE = (
    "Your turn ended but `trace.md` and/or `answer.txt` do not yet exist in the "
    "current working directory, so the task is incomplete. Do NOT wait for any "
    "plan approval and do NOT stop to load more skills — continue executing the "
    "analysis immediately from where you left off, then WRITE both `trace.md` "
    "(with the required sections) and `answer.txt` to the current working "
    "directory before ending your turn. If a plan/approval tool is pending, "
    "treat it as already approved and proceed."
)


def _admin_root() -> Path:
    return Path(os.environ.get("OMICOS_ADMIN_ROOT", str(_DEFAULT_ADMIN_ROOT)))


def _build_merged_catalog(cache_dir: Path) -> Path:
    """Flatten `omicos-admin/domains/*/agents/*.md` into one `agents/` dir.

    The admin catalog moved to a per-domain layout, but the omicos runner's
    overlay wants a single flat `agents/` directory (this mirrors what
    slice_reg_test pre-materialized as `_agents_catalog_src/agents`). We rebuild
    it into a repo-local cache so the runner's OMICOS_BIOMNIBENCH_AGENTS_DIR
    resolves to a real flat dir. Rebuilt every process (cheap; ~80 files).
    """

    admin = _admin_root()
    agents_out = cache_dir / "agents"
    if agents_out.exists():
        shutil.rmtree(agents_out)
    agents_out.mkdir(parents=True)
    n = 0
    for dom in _DOMAINS:
        src = admin / "domains" / dom / "agents"
        if not src.is_dir():
            continue
        for md in src.glob("*.md"):
            dest = agents_out / md.name
            if not dest.exists():  # first domain wins on name clash
                shutil.copy2(md, dest)
                n += 1
    if n == 0:
        raise AdapterUnavailable(
            f"no omicos-admin agents found under {admin}/domains/*/agents"
        )
    return agents_out


def _skill_roots() -> str:
    admin = _admin_root()
    return ":".join(str(admin / "domains" / d / "skills") for d in _DOMAINS)


class OmicosAdapter:
    id = "omicos"
    kind = "omicos"

    def __init__(self, spec: dict):
        self.spec = spec
        self.model = dict(spec.get("model") or {})
        self._bin = Path(os.environ.get("OMICOS_BIN", str(_DEFAULT_OMICOS_BIN)))

    def available(self) -> bool:
        return self._bin.is_file() and os.access(self._bin, os.X_OK)

    def run(
        self,
        *,
        instruction: str,
        workspace: Path,
        cell_dir: Path,
        model: dict,
    ) -> RunResult:
        if not self.available():
            raise AdapterUnavailable(f"omicos binary not executable: {self._bin}")

        from .._biomni import ob_client, ob_runner
        from ..prompts import build_prompt

        # Overlay: merged admin agent catalog + domain skills. Set here (not at
        # import) so a caller can override OMICOS_ADMIN_ROOT per run.
        catalog = _build_merged_catalog(cell_dir / "_omicos_catalog")
        os.environ["OMICOS_BIN"] = str(self._bin)
        os.environ["OMICOS_BIOMNIBENCH_AGENTS_DIR"] = str(catalog)
        os.environ["OMICOS_BIOMNIBENCH_SKILLS_DIR"] = _skill_roots()
        # Force the omicdev kernel. secrets.env may export
        # OMICOS_KERNEL_PYTHON=…/omicverse, whose scanpy/omicverse import hangs
        # at kernel spawn (serve then never becomes usable and the turn dies with
        # no_output). omicdev carries the same scientific stack and starts
        # reliably (it's what the working runs used). Override, don't setdefault.
        os.environ["OMICOS_KERNEL_PYTHON"] = _DEFAULT_KERNEL_PY

        # …but OMICOS_KERNEL_PYTHON is only step 2 of the runner's kernel
        # resolution. Step 1 is a `.kernel_choice` JSON dropped by a past
        # `kernel_select`, read from `cwd/.omicos`, then `$HOME/.omicos`, then
        # `$OMICOS_LOCAL_HOME` — first hit wins, BEFORE the env var. A stale
        # ~/.omicos/.kernel_choice pinning …/omicverse therefore silently beats
        # our env override on every cell. serve() runs with cwd=workspace, and
        # cwd/.omicos is the first root checked, so drop a per-run choice there
        # to deterministically pin omicdev without mutating the user's global
        # ~/.omicos (see native.rs resolve_python_interpreter / kernel_choice_roots).
        ws_omicos = workspace / ".omicos"
        ws_omicos.mkdir(exist_ok=True)
        (ws_omicos / ".kernel_choice").write_text(
            json.dumps({"kernel_id": "omicdev", "python_path": _DEFAULT_KERNEL_PY}),
            encoding="utf-8",
        )

        model_cfg = {**self.model, **(model or {})}
        prompt = build_prompt(instruction, flavor="omicos")

        # Disable cloud CONVERSATION sync. omicos-biomnibench's runner already
        # forces AGENTS/SKILLS/MODELS/MEMORY offline but leaves conversation sync
        # on, so a logged-in serve boots, `legacy_store_discovery` scans every
        # past workspace `.omicos` on disk, and tries to cloud-sync the recovered
        # (stranded) conversations to OmicOS Server. Once enough have accumulated
        # across runs this hangs the serve mid-startup — the turn then dies with
        # "stream lost, reconnect budget exhausted: Connection refused" and the
        # cell scores no_output (see cloud_sync_conversations.rs OMICOS_SYNC_DISABLE).
        started = time.monotonic()
        timeout_s = float(model_cfg.get("timeout_s", 25000))
        # One session id for the whole cell so a follow-up "continue" turn
        # RESUMES the same conversation (full history intact) rather than
        # starting fresh (see run_turn's session_id contract).
        session_id = uuid.uuid4().hex
        try:
            with ob_runner.serve(
                workspace,
                log_path=cell_dir / "omicos.log",
                # extra_env is the RELIABLE override point (runner.serve applies
                # it last, over its own os.environ-derived kernel_python). Setting
                # OMICOS_KERNEL_PYTHON in os.environ alone doesn't stick under the
                # matrix's ThreadPoolExecutor (shared process env) when secrets.env
                # exports omicverse — force omicdev here so the kernel is stable.
                extra_env={"OMICOS_SYNC_DISABLE": "1",
                           "OMICOS_KERNEL_PYTHON": _DEFAULT_KERNEL_PY},
                health_timeout_s=600.0,
            ) as proc:
                turn = ob_client.run_turn(
                    base_url=proc.base_url,
                    agent_id="vertical_agent_selector",
                    user_message=prompt,
                    model_cfg=model_cfg,
                    sse_log=cell_dir / "sse.log",
                    trajectory_log=cell_dir / "trajectory.jsonl",
                    timeout_s=timeout_s,
                    session_id=session_id,
                )

                # Continue-nudge. A recurring no_output mode is the agent ENDING
                # its turn cleanly (SSE `done`, no error) without ever writing the
                # deliverables — it stalls on a plan-approval gate, churns through
                # skill loads until the turn budget is gone, or signs off with a
                # bare "let me now run X" text and no tool call. The turn-hub then
                # closes and the cell scores 0 despite the pipeline working (the
                # sister full-run cells complete). When the files are missing after
                # a NON-fatal turn end, re-POST a short "continue, you haven't
                # written the files" turn on the SAME session so the agent resumes
                # with full context and finishes. Bounded retries; skip if the
                # turn died on a real stream error (serve is likely gone).
                for attempt in range(_MAX_CONTINUE_NUDGES):
                    have = ((workspace / "trace.md").is_file()
                            and (workspace / "answer.txt").is_file())
                    if have or turn.error:
                        break
                    turn = ob_client.run_turn(
                        base_url=proc.base_url,
                        agent_id="vertical_agent_selector",
                        user_message=_CONTINUE_NUDGE,
                        model_cfg=model_cfg,
                        sse_log=cell_dir / f"sse_nudge{attempt + 1}.log",
                        trajectory_log=cell_dir
                        / f"trajectory_nudge{attempt + 1}.jsonl",
                        timeout_s=timeout_s,
                        session_id=session_id,
                    )
        except Exception as e:  # serve/turn failure — surfaced, not swallowed
            return RunResult(error=f"{type(e).__name__}: {e}",
                             elapsed_s=time.monotonic() - started)

        return RunResult(
            final_text=turn.final_text,
            final_answer=turn.final_answer,
            tool_calls=turn.tool_calls,
            events=turn.events,
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
            error=turn.error,
            elapsed_s=turn.elapsed_s,
        )
