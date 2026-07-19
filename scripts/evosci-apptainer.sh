#!/bin/bash
# Run EvoScientist inside an Apptainer container with glibc >= 2.18.
#
# WHY: EvoScientist's code-interpreter sandbox (quickjs_rs -> wasmtime) dlopens a
# native lib that needs GLIBC_2.18, but Sherlock's el7 nodes ship glibc 2.17, so
# `EvoSci` crashes at startup on bare metal (docs/parity-caveats.md §2b). We run
# the SAME already-installed EvoScientist venv, but under a newer-glibc runtime.
# The venv python + site-packages live on $SCRATCH / $HOME (both bind-mounted),
# and the container only supplies the newer libc.
#
# Point the evoscientist adapter at this script:
#     export EVOSCI_BIN=/path/to/analysis/omicos_dev/biology_bench/scripts/evosci-apptainer.sh
#
# A leading `--probe-wasmtime` arg runs the in-container import check the adapter
# uses for availability (instead of driving the agent).
set -euo pipefail

SIF="${EVOSCI_SIF:-/path/to/analysis/omicos_dev/biology_bench/containers/ubuntu2204.sif}"
EVOSCI_ENTRY="${EVOSCI_ENTRY:-/path/to/.uv/bin/EvoSci}"
VENV_PY="$(dirname "$(readlink -f "$EVOSCI_ENTRY")")/python"

export APPTAINER_CACHEDIR="${APPTAINER_CACHEDIR:-/path/to/.apptainer}"
# Bind $SCRATCH (venv, caches, config, workspaces) + $HOME (uv-managed cpython).
BINDS="--bind /path/to --bind ${HOME}"

if [ "${1:-}" = "--probe-wasmtime" ]; then
  exec apptainer exec $BINDS "$SIF" "$VENV_PY" -c "import wasmtime"
fi

# apptainer passes host env through by default (DEEPSEEK_API_KEY, XDG_CONFIG_HOME,
# EVOSCIENTIST_HOME, OPENAI_* …) and preserves the (bind-mounted) CWD.
exec apptainer exec $BINDS "$SIF" "$EVOSCI_ENTRY" "$@"
