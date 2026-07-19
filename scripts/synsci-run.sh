#!/bin/bash
# Drive synthetic-sciences/openscience headlessly, inside the glibc>=2.18
# Apptainer container. The product's primary UX is a browser workspace, but its
# CLI ships a documented headless path: `openscience run --format json` streams
# line-delimited JSON events and runs the same agent core the UI drives.
#
# We use the published, self-contained compiled binary (from `bun add
# @synsci/openscience` -> the @synsci/openscience-linux-x64 platform package),
# NOT a source checkout — the monorepo's bun workspace doesn't install cleanly
# on Lustre, and the release binary bundles all deps.
#
# Usage:
#   synsci-run.sh --probe
#   synsci-run.sh run <workspace> <model> <prompt_file> [agent]
set -euo pipefail

SIF="${OSCI_SIF:-/path/to/analysis/omicos_dev/biology_bench/containers/ubuntu2204.sif}"
OSCI="${SYNSCI_BIN:-/path/to/software/synsci-pkg/node_modules/@synsci/openscience-linux-x64/bin/openscience}"
OSHOME="${OSCI_OSHOME:-/path/to/.oshome}"
# Scientific Python kernel (bare ubuntu image has no python); omicdev runs fine
# under the container's newer glibc — same env omicos uses.
KERNEL_BIN="${OSCI_KERNEL_BIN:-/path/to/env/omicdev/bin}"
BIND="--bind /path/to"

if [ "${1:-}" = "--probe" ]; then
  exec apptainer exec $BIND "$SIF" bash -c "HOME='$OSHOME' '$OSCI' --version"
fi

if [ "${1:-}" != "run" ]; then
  echo "usage: $0 --probe | run <workspace> <model> <prompt_file> [agent]" >&2
  exit 2
fi
WS="$2"; MODEL="$3"; PROMPT_FILE="$4"; AGENT="${5:-research}"

exec apptainer exec $BIND "$SIF" bash -c "
  export HOME='$OSHOME'
  export DEEPSEEK_API_KEY='${DEEPSEEK_API_KEY:-}'
  export PATH='$KERNEL_BIN':\$PATH
  cd '$WS'
  exec '$OSCI' run --model '$MODEL' --agent '$AGENT' --format json \"\$(cat '$PROMPT_FILE')\"
"
