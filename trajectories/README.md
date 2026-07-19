# Trajectories

Per-cell agent outputs for every (backend, task), curated for publication.

## Layout

```
trajectories/<backend>/<task>/
    trace.md         # the agent's structured analytical trace
    answer.txt       # the agent's final answer
    grade.json       # score + status + grader_notes + criteria
    trajectory.jsonl # (optional) raw event stream
```

Produced by `scripts/export_trajectories.py`, which copies **only** the files
above. It does **not** include the task `instruction.md` or the BiomniBench-DA
rubric (dataset content), nor the staged `workspace/` inputs.

## Where to get them

The trajectories are **not stored in git** (110 MB of per-cell output). They are
published as a HuggingFace dataset:

**→ https://huggingface.co/datasets/omicverse/BiomniBench-AI4S**

```bash
huggingface-cli download omicverse/BiomniBench-AI4S --repo-type dataset \
    --local-dir trajectories/
```

Each `<backend>/<task>/` holds `trace.md`, `answer.txt`, `grade.json`, and
(where available) `trajectory.jsonl`. The omicos trajectories are passed through
the redaction step below before upload.

## omicos redaction

OmicOS's agent/skill definitions (`omicos-admin`) are private. `omicos`
trajectories are passed through `scripts/redact_omicos_trajectories.py`, which
withholds only the proprietary bodies (loaded SKILL.md text, the agent catalog,
skill reference/asset content, and any asset source pasted into executed code) —
replacing each with a short notice. Agent/skill NAMES, the tool-call structure,
`registry_lookup` output, and every analysis step (`run_python_code` + outputs +
results) are kept, so the run remains fully followable and reproducible.
