#!/bin/bash
# Drive ai4s-research/open-science headlessly via its bundled OpenCode core,
# inside the glibc>=2.18 Apptainer container (el7 nodes ship glibc 2.17, too old
# for the opencode binary). The Tauri desktop shell is bypassed entirely: we run
# the same opencode binary + the project's own skills/AGENTS overlay that the
# desktop app would spawn (apps/desktop/src-tauri/src/runtime.rs spawns
# `opencode serve`; here we use `opencode run` single-shot).
#
# Usage:
#   opencode-ai4s.sh --probe                     # runnability check (rc 0 = ok)
#   opencode-ai4s.sh run <workspace> <model> <prompt_file>
#
# DEEPSEEK_API_KEY is inherited from the caller's env (apptainer passes host env
# through by default) and is what opencode's built-in deepseek provider reads.
set -euo pipefail

SIF="${OSCI_SIF:-/path/to/analysis/omicos_dev/biology_bench/containers/ubuntu2204.sif}"
OC="${OPENCODE_BIN:-/path/to/software/opencode/opencode}"
OSHOME="${OSCI_OSHOME:-/path/to/.oshome}"
BIND="--bind /path/to"

mkdir -p "$OSHOME/.config/opencode"
# Minimal config: opencode's built-in deepseek provider + models.dev catalog
# already expose deepseek-v4-pro; auth is via the DEEPSEEK_API_KEY env var.
if [ ! -f "$OSHOME/.config/opencode/opencode.json" ]; then
  printf '{"$schema":"https://opencode.ai/config.json"}' > "$OSHOME/.config/opencode/opencode.json"
fi

if [ "${1:-}" = "--probe" ]; then
  exec apptainer exec $BIND "$SIF" bash -c "HOME='$OSHOME' '$OC' --version"
fi

if [ "${1:-}" != "run" ]; then
  echo "usage: $0 --probe | run <workspace> <model> <prompt_file>" >&2
  exit 2
fi
WS="$2"; MODEL="$3"; PROMPT_FILE="$4"

# opencode wants a git repo; --format json streams line-delimited events to
# stdout (captured as the trajectory), --print-logs sends diagnostics to stderr.
# The ubuntu2204 image is bare (no Python). BiomniBench tasks need a scientific
# Python stack, so put the omicdev conda env (pandas/scanpy/numpy/…, same env
# omicos uses) on PATH — it runs fine under the container's newer glibc. This is
# the analysis kernel the agent's bash/python tools use.
KERNEL_BIN="${OSCI_KERNEL_BIN:-/path/to/env/omicdev/bin}"
exec apptainer exec $BIND "$SIF" bash -c "
  export HOME='$OSHOME'
  export DEEPSEEK_API_KEY='${DEEPSEEK_API_KEY:-}'
  export PATH='$KERNEL_BIN':\$PATH
  cd '$WS'
  git init -q 2>/dev/null || true
  exec '$OC' run --print-logs --format json -m '$MODEL' \"\$(cat '$PROMPT_FILE')\"
"
