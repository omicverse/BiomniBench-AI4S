# Building & running the competitor agents from source

Every competitor is driven **headlessly** over a staged task workspace by a thin
adapter (`src/biology_bench/adapters/`) + a launcher (`scripts/*.sh` or a driver
`.py`). This doc is the reproducible "from GitHub to a runnable backend" recipe
for each of the six competitors, with the real gotchas we hit.

**Common environment.** Sherlock compute nodes run CentOS 7 (**glibc 2.17**),
which is too old for several of these agents (they need ≥ 2.18/2.28/2.35). The
fix is a one-time Apptainer container that only supplies a newer libc while the
agent's own install lives on `$SCRATCH` and is bind-mounted in:

```bash
export APPTAINER_CACHEDIR=/path/to/.apptainer
apptainer pull containers/ubuntu2204.sif docker://ubuntu:22.04   # glibc 2.35
```

**Model parity.** Every backend runs `deepseek-v4-pro` — natively (biomni,
synsci, ai4s) or via a gateway that maps an Anthropic/OpenAI model id to it
(claude). Set `DEEPSEEK_API_KEY` / `DEEPSEEK_API_BASE` in `.env`.

---

## 1. EvoScientist — `EvoScientist/EvoScientist`

Independent LangGraph agent, headless CLI `EvoSci`.

```bash
# install (uv tool; pin py3.11)
export UV_TOOL_DIR=/path/to/.uv/tools UV_TOOL_BIN_DIR=/path/to/.uv/bin
uv tool install --python 3.11 EvoScientist         # provides `EvoSci`

# provider parity
EvoSci config set provider deepseek
EvoSci config set model deepseek-v4-pro
EvoSci config set deepseek_api_key "$DEEPSEEK_API_KEY"
```

- **glibc:** EvoScientist's code-interpreter sandbox (`quickjs_rs` → `wasmtime`)
  dlopens a lib needing GLIBC_2.18 → **run it through `scripts/evosci-apptainer.sh`**
  (bind-mounts the installed venv into ubuntu2204.sif). Point the adapter at it:
  `export EVOSCI_BIN=$PWD/scripts/evosci-apptainer.sh`.
- **Concurrency:** EvoSci starts a single langgraph dev server on a fixed port
  (6174) bound to one workspace, so parallel cells collide. The adapter gives
  each cell a unique `EVOSCIENTIST_LANGGRAPH_DEV_PORT` + its own
  `EVOSCIENTIST_HOME` (see `evoscientist_adapter.py`); `--mode run` cannot be
  combined with `--workdir`.

## 2. Biomni (OSS) — `snap-stanford/biomni`

The reference agent the tasks originate from (A1 agent).

```bash
# its own conda env
conda create -n biomni_base python=3.11 -y && conda activate biomni_base
pip install biomni --upgrade
```

- Driven out-of-process (its langgraph stack clashes with the harness python) by
  `scripts/biomni_run.py`, which instantiates `A1(llm='deepseek-v4-pro',
  source='Custom', base_url=$DEEPSEEK_API_BASE, api_key=$DEEPSEEK_API_KEY,
  expected_data_lake_files=[])` — the `Custom` source gives DeepSeek parity, and
  `expected_data_lake_files=[]` skips the ~11 GB data-lake download.
- Set `BIOMNI_PYTHON=/path/to/biomni_base/bin/python`. CPU-only; 50-way parallel
  runs cleanly under Slurm (`sbatch --cpus-per-task=50`).

## 3. Claude / CSSwitch — `SuperJJ007/CSswitch` (Claude Code core)

"Claude on DeepSeek": the Claude Code CLI routed through CSswitch's gateway,
which maps the requested `claude-opus-4-8` → `deepseek-v4-pro`.

```bash
# Claude Code CLI
npm install -g @anthropic-ai/claude-code                 # provides `claude`

# CSswitch gateway (Rust)
git clone https://github.com/SuperJJ007/CSswitch && cd CSswitch
cargo build --release -p csswitch-gateway                # binary: desktop/gateway
```

- **el7 build:** `skill_install.rs` calls `renameat2` (glibc ≥ 2.28); patch it to
  pre-check + fall back to `std::fs::rename` so it links on el7.
- Run inside ubuntu2204.sif via `scripts/claude-csswitch.sh` (sets
  `ANTHROPIC_BASE_URL` → local gateway, `ANTHROPIC_MODEL=claude-opus-4-8`).
- Note: this is Claude **Code**, not the closed-source Claude **Science** desktop
  app — that app has no headless task CLI (browser-UI only) and its claude.ai
  account endpoints 401 without a live login, so it is not benchmarkable here.

## 4. SynSci Open-Science — `synthetic-sciences/openscience`

Browser workbench with a documented headless CLI (`openscience run --format json`).

```bash
# use the published platform binary (the bun workspace doesn't install on Lustre)
export BUN_INSTALL=/path/to/bun
bun add @synsci/openscience         # pulls @synsci/openscience-linux-x64
# binary: node_modules/@synsci/openscience-linux-x64/bin/openscience
```

- Run through `scripts/synsci-run.sh` (ubuntu2204.sif). Uses the scientific
  kernel python (bare ubuntu has none). Config: deepseek provider, `agent: research`.

## 5. AI4S Open-Science — `ai4s-research/open-science` (OpenCode core)

Electron/Tauri desktop app whose core is `opencode`; driven headlessly via the
opencode binary + ai4s's own skills/AGENTS overlay (bypassing the GUI).

```bash
git clone https://github.com/ai4s-research/open-science
# fetch the opencode binary its runtime spawns (`opencode serve`); here we use
# `opencode run` single-shot with the project's overlay:
#   OPENCODE_BIN=/path/to/opencode/opencode
```

- Run through `scripts/opencode-ai4s.sh` (ubuntu2204.sif). opencode reads its
  built-in deepseek provider + `DEEPSEEK_API_KEY`; model config is a generated
  `opencode.json` (not ANTHROPIC_* env).

## 6. Wisp Science — `xuzhougeng/wisp-science`

Local-first desktop assistant with a native Rust CLI; runs on el7 directly (no
container).

```bash
git clone https://github.com/xuzhougeng/wisp-science && cd wisp-science
export CARGO_HOME=/path/to/.cargo RUSTUP_HOME=/path/to/.rustup
cargo build --release                       # binary: target/release/wisp-science
```

- Run through `scripts/wisp-run.sh` (native, no apptainer). It wires a bundled
  Python + R kernel and ~230 bio MCP tools; a prompt is fed single-line via
  stdin followed by `/q`. DeepSeek via its OpenAI-compatible provider path.

---

## Not benchmarkable headlessly (documented for completeness)

- **`aipoch/open-science`** — Electron GUI, no CLI. Its core wraps the SAME two
  engines already in the table (`@agentclientprotocol/claude-agent-acp` = Claude
  Code, or `opencode`), so it adds no new engine — only an overlay. Would require
  driving its ACP runtime under xvfb.
- **Claude Science** (closed-source desktop) — see §3.

For any GUI-only agent you can still score it: run it on a desktop, drop its
`trace.md` + `answer.txt` into `runs/<id>/<task>/manual/`, and grade with the
`import-artifacts` path.
