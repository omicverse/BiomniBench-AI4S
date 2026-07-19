"""Adapter contract shared by every science-agent backend.

An adapter's whole job is the *driving* step: given a staged task workspace and
the user prompt, run the agent until it writes `trace.md` + `answer.txt` into
that workspace. Grading is done by the caller (matrix.py) via the shared
omicos-biomnibench grader, so an adapter never scores anything itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class RunResult:
    """Normalized outcome of one agent run over one task.

    Field names deliberately mirror omicos-biomnibench's `TurnResult` so the
    omicos adapter is a straight copy and other adapters fill what they can
    (unknown counters stay 0).
    """

    final_text: str = ""
    final_answer: str = ""
    tool_calls: int = 0
    events: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    elapsed_s: float = 0.0


class AdapterUnavailable(RuntimeError):
    """Raised by `run()` when a backend cannot execute in this environment
    (e.g. a desktop-only app on a headless node, or a missing CLI)."""


@runtime_checkable
class Adapter(Protocol):
    id: str
    kind: str

    def available(self) -> bool:
        """True if this backend can actually be driven here right now."""
        ...

    def run(
        self,
        *,
        instruction: str,
        workspace: Path,
        cell_dir: Path,
        model: dict,
    ) -> RunResult:
        """Drive the agent over `workspace`; it must leave `trace.md` +
        `answer.txt` behind. `cell_dir` is the per-cell output dir for logs."""
        ...


def build_adapter(spec: dict) -> Adapter:
    """Factory: turn one `backends.yaml` entry into an Adapter instance."""

    kind = spec.get("kind")
    # Local imports avoid importing heavy deps (httpx/omicos) for kinds unused.
    if kind == "omicos":
        from .omicos_adapter import OmicosAdapter

        return OmicosAdapter(spec)
    if kind == "evoscientist":
        from .evoscientist_adapter import EvoScientistAdapter

        return EvoScientistAdapter(spec)
    if kind == "ai4s":
        from .openscience_ai4s_adapter import OpenScienceAI4SAdapter

        return OpenScienceAI4SAdapter(spec)
    if kind == "synsci":
        from .openscience_synsci_adapter import OpenScienceSynsciAdapter

        return OpenScienceSynsciAdapter(spec)
    if kind == "wisp":
        from .wisp_adapter import WispAdapter

        return WispAdapter(spec)
    if kind == "claude_csswitch":
        from .claude_csswitch_adapter import ClaudeCSswitchAdapter

        return ClaudeCSswitchAdapter(spec)
    if kind == "biomni":
        from .biomni_adapter import BiomniAdapter

        return BiomniAdapter(spec)
    if kind == "desktop":
        from .desktop_stub import DesktopStubAdapter

        return DesktopStubAdapter(spec)
    raise ValueError(f"unknown backend kind: {kind!r} (in {spec.get('id')!r})")
