#!/bin/bash
# Drive xuzhougeng/wisp-science headlessly via its `wisp-science` CLI binary
# (crate wisp-cli, "Headless wisp-science agent"). Unlike the other competitors,
# wisp is a Rust native binary compiled on this el7 host, so it runs DIRECTLY —
# no Apptainer container needed.
#
# The CLI is an stdin REPL (reads one line per turn; /q quits), so the prompt is
# fed single-line via stdin followed by /q. It wires a bundled Python + R kernel
# and ~230 bioinformatics MCP tools. Model parity: WISP_PROVIDER=openai +
# WISP_API_URL=DeepSeek + WISP_MODEL=deepseek-v4-pro, authed by DEEPSEEK_API_KEY.
#
# Usage:
#   wisp-run.sh --probe
#   wisp-run.sh run <workspace> <model> <prompt_file>   # prompt_file must be ONE line
set -euo pipefail

WISP="${WISP_BIN:-/path/to/software/wisp-target/release/wisp-science}"
WISP_ROOT="${WISP_ROOT:-/path/to/analysis/omicos_dev/biology_bench/vendor/wisp}"
KERNEL_BIN="${OSCI_KERNEL_BIN:-/path/to/env/omicdev/bin}"

if [ "${1:-}" = "--probe" ]; then
  [ -x "$WISP" ] && [ -f "$WISP_ROOT/python/kernel_worker.py" ] && exit 0
  exit 1
fi

if [ "${1:-}" != "run" ]; then
  echo "usage: $0 --probe | run <workspace> <model> <prompt_file>" >&2
  exit 2
fi
WS="$2"; MODEL="$3"; PROMPT_FILE="$4"

cd "$WS"
export WISP_API_KEY="${DEEPSEEK_API_KEY:-}"
export WISP_PROVIDER=openai
export WISP_MODEL="$MODEL"
export WISP_API_URL="${DEEPSEEK_API_BASE:-https://api.deepseek.com/v1}"
export WISP_SKILLS_PATH="$WISP_ROOT/skills"
export WISP_KERNEL_WORKER="$WISP_ROOT/python/kernel_worker.py"
export PATH="$KERNEL_BIN:$PATH"
export WISP_MAX_ITER="${WISP_MAX_ITER:-100}"

# One-line prompt, then /q to end the REPL after the turn completes.
printf '%s\n/q\n' "$(cat "$PROMPT_FILE")" | exec "$WISP"
