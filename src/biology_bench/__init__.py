"""biology_bench — cross-agent BiomniBench-DA comparison harness.

Reuses omicos-biomnibench's dataset staging + rubric grader verbatim (they are
already agent-agnostic — the grader only reads `trace.md`+`answer.txt` from the
workspace) and adds a pluggable `adapters/` layer so several science agents can
be driven over the *same* tasks and scored by the *same* judge.
"""

__version__ = "0.1.0"
