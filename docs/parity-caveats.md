# Parity caveats & deviations log

biology_bench compares different science agents on the *same* BiomniBench-DA
tasks with the *same* rubric judge. For the comparison to be fair, everything
except the agent must be held constant. Where that isn't fully achievable, the
deviation is logged here (same convention as
`omicos-biomnibench/docs/grading-deviations.md`). Add a dated entry whenever you
change a knob that could move a score.

## Held constant across every backend

- **Tasks** — identical. Loaded via `omicos-biomnibench`'s `dataset.load_tasks`
  / `stage_task` (imported in-place, not copied). Each backend gets a fresh copy
  of the same `environment/` + `instruction.md`.
- **Rubric judge** — identical. `configs/models.yaml` pins DeepSeek v4-pro, and
  every cell is graded by `omicos-biomnibench`'s `grader.grade`. This is the same
  judge omicos-biomnibench uses, so a biology_bench omicos score is directly
  comparable to an omicos-biomnibench score.
- **Pass cutoff** — `score >= 0.70` for all backends.
- **Output contract** — every backend is told to write `trace.md` + `answer.txt`
  to its working dir; the grader reads only those two files.

## Known deviations

### 1. Prompt flavor (omicos vs generic)

The omicos backend receives an extra "Multi-specialist orchestration" paragraph
naming its `call_agent` handoffs (`clinical_translator_pro`, `scientific_writer`)
— this is load-bearing for the `vertical_agent_selector` agent and is lifted
verbatim from omicos-biomnibench. Third-party agents receive the neutral
`generic` flavor without omicos tool names. **The task text and rubric are
byte-identical across flavors**; only the closing agent-operating notes differ.
See `src/biology_bench/prompts.py`.

### 2. Model parity (EvoScientist)

omicos runs on `deepseek-v4-pro`. EvoScientist turns out to support DeepSeek
**natively** (`EvoSci config set provider deepseek` / `model deepseek-v4-pro` /
`deepseek_api_key …`), so exact model parity with omicos IS reachable — the
`_submit.sbatch` configures exactly that before running. (The adapter also
forwards `DEEPSEEK_API_BASE`/`KEY` as `OPENAI_BASE_URL`/`KEY` as a belt-and-
suspenders fallback.) EvoScientist state (config + `sessions.db`) is redirected
to `$SCRATCH` via `XDG_CONFIG_HOME`/`EVOSCIENTIST_HOME` to stay off `$HOME`.

### 2b. EvoScientist on Sherlock: el7 GLIBC wall → RESOLVED via Apptainer

**Status: RESOLVED.** EvoScientist runs on Sherlock through an Apptainer
container (glibc 2.35). Verified end-to-end: `EvoSci -p … --output-format
stream-json` inside the container drives DeepSeek and writes files to a
`$SCRATCH` workspace. Wire it with:

```bash
export EVOSCI_BIN=…/biology_bench/scripts/evosci-apptainer.sh
```

The `_submit.sbatch` sets this automatically. The launcher runs the *same*
already-installed EvoScientist venv (on `$SCRATCH`/`$HOME`, bind-mounted) but
under the container's newer glibc; the adapter probes runnability through the
launcher (`--probe-wasmtime`). Image: `containers/ubuntu2204.sif` (rebuild with
`apptainer pull containers/ubuntu2204.sif docker://ubuntu:22.04`).

The underlying incompatibility (kept here for the record): EvoScientist's
code-interpreter middleware
(`EvoScientist/middleware/code_interpreter.py` → `langchain_quickjs` →
`quickjs_rs` → `import wasmtime`) dlopens `_libwasmtime.so`, which requires
`GLIBC_2.18`. Sherlock's CentOS-7 / el7 nodes ship glibc **2.17**, so the import
crashes at startup:

```
OSError: /lib64/libc.so.6: version `GLIBC_2.18' not found
  (required by …/wasmtime/linux-x86_64/_libwasmtime.so)
```

This is not an optional feature — quickjs is EvoScientist's tool-execution
sandbox — so it cannot be stubbed away without disabling the agent's core loop.
Without the container, the `evoscientist` adapter's `available()` (probing
`import wasmtime` in the host venv python) returns False on el7, so the
leaderboard shows `evoscientist` as **unavailable** rather than emitting a
traceback into a graded cell. With `EVOSCI_BIN` pointed at the container
launcher, the probe runs inside the container and passes — see the RESOLVED note
above.

### 3. Desktop backends are not run headlessly

`openscience_synsci` (npm→browser), `openscience_ai4s` (Tauri desktop) and
`openscience_aipoch` (desktop GUI) have no batch-drivable headless CLI, so they
are `enabled: false` and reported as `unavailable`. They can still be scored on
the identical rubric via the bring-your-own-artifact path — see
`running-competitors.md` and `biology-bench import-artifacts`. Any such run is a
*manual* run, not an automated one; note that when comparing.

### 4. Tool/token counters are backend-specific

omicos counters come from the SSE stream (exact). EvoScientist counters are a
best-effort parse of its `stream-json` events (schema not contractual);
unknown counters are 0. Do not compare token/tool counts across backends as if
they were measured the same way — compare **scores**.
