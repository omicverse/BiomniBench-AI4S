"""Import bridge to omicos-biomnibench.

biology_bench does NOT vendor a copy of the dataset loader or grader — it
imports them in-place from the sibling `omicos-biomnibench/src` tree (the same
`sys.path.insert` trick `omicos-covid/slice_reg_test/_run.py` uses). This keeps
a single source of truth: the tasks every backend runs and the rubric judge
every backend is scored by are literally the same code, so a cross-agent score
delta is attributable to the agent, not to a diverged harness.

Set `OMICOS_BIOMNIBENCH_ROOT` to override the location (defaults to the sibling
clone next to this repo).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "omicos-biomnibench"


def _biomni_root() -> Path:
    root = Path(os.environ.get("OMICOS_BIOMNIBENCH_ROOT", str(_DEFAULT_ROOT)))
    src = root / "src"
    if not (src / "omicos_biomnibench" / "grader.py").is_file():
        raise RuntimeError(
            f"omicos-biomnibench not found at {root} (looked for src/"
            "omicos_biomnibench/grader.py). Clone it next to biology_bench or "
            "export OMICOS_BIOMNIBENCH_ROOT=<path>."
        )
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return root


BIOMNI_ROOT = _biomni_root()

# Re-exported so the rest of biology_bench imports through this single shim.
from omicos_biomnibench import client as ob_client  # noqa: E402
from omicos_biomnibench import dataset as ob_dataset  # noqa: E402
from omicos_biomnibench import grader as ob_grader  # noqa: E402
from omicos_biomnibench import runner as ob_runner  # noqa: E402

__all__ = ["BIOMNI_ROOT", "ob_client", "ob_dataset", "ob_grader", "ob_runner"]
