#!/bin/bash
# "Claude Science on DeepSeek", headless, inside the glibc>=2.18 Apptainer
# container. Claude Science itself is a closed-source macOS app, so this is the
# closest headless equivalent: Claude's own agent CLI (Claude Code) driven
# through CSswitch's gateway, which the CSswitch desktop app uses to route
# Claude's Anthropic requests to an alternative provider.
#
#   claude (Claude Code) --ANTHROPIC_BASE_URL--> csswitch-gateway --> DeepSeek
#
# The gateway maps the requested `claude-opus-4-8` model to `deepseek-v4-pro`
# (CSswitch's built-in mapping), so this backend runs the SAME model as the
# others. gateway is CSswitch's own Rust binary (desktop/gateway), built here
# with the el7 renameat2 workaround (see skill_install.rs edit).
#
# Usage:
#   claude-csswitch.sh --probe
#   claude-csswitch.sh run <workspace> <prompt_file>
set -uo pipefail

SIF="${OSCI_SIF:-/path/to/analysis/omicos_dev/biology_bench/containers/ubuntu2204.sif}"
GW="${CSSWITCH_GATEWAY_BIN:-/path/to/software/csswitch-gw-target/release/csswitch-gateway}"
CLAUDE_BIN="${CLAUDE_BIN:-/path/to/npm-global/bin/claude}"
NODE_BIN="${NODE_BIN:-/share/software/user/open/nodejs/20.20.0/bin}"
KERNEL_BIN="${OSCI_KERNEL_BIN:-/path/to/env/omicdev/bin}"
CFG_DIR="${CLAUDE_CONFIG_DIR:-/path/to/.claude_science_home}"
BIND="--bind /path/to --bind /share/software"

if [ "${1:-}" = "--probe" ]; then
  [ -x "$GW" ] && [ -x "$CLAUDE_BIN" ] && [ -x "$NODE_BIN/node" ] && exit 0
  exit 1
fi
if [ "${1:-}" != "run" ]; then
  echo "usage: $0 --probe | run <workspace> <prompt_file>" >&2
  exit 2
fi
WS="$2"; PROMPT_FILE="$3"
PORT=$(( 18000 + (RANDOM % 1500) ))
mkdir -p "$CFG_DIR"

exec apptainer exec $BIND "$SIF" bash -c "
  export PATH='$NODE_BIN':'$KERNEL_BIN':\$PATH
  export DEEPSEEK_API_KEY='${DEEPSEEK_API_KEY:-}'
  export CLAUDE_CONFIG_DIR='$CFG_DIR'
  # Start the CSswitch gateway (Anthropic->DeepSeek) on a private port.
  '$GW' --provider deepseek --port $PORT >/tmp/csswitch_gw_$PORT.log 2>&1 &
  GWPID=\$!
  # Wait for health via node (the base image has no curl).
  for i in \$(seq 1 30); do
    node -e \"require('http').get('http://127.0.0.1:$PORT/health',r=>process.exit(r.statusCode==200?0:1)).on('error',()=>process.exit(1))\" 2>/dev/null && break
    sleep 1
  done
  cd '$WS'
  export ANTHROPIC_BASE_URL='http://127.0.0.1:$PORT'
  export ANTHROPIC_API_KEY='routed-via-gateway'
  '$CLAUDE_BIN' -p \"\$(cat '$PROMPT_FILE')\" \
    --model claude-opus-4-8 --dangerously-skip-permissions \
    --add-dir '$WS' --output-format stream-json --verbose
  RC=\$?
  kill \$GWPID 2>/dev/null
  exit \$RC
"
