#!/usr/bin/env python
"""Headless driver for snap-stanford/biomni (A1 agent), run INSIDE the
`biomni_base` conda env (biomni 0.0.8) as a subprocess of the harness.

Usage:
    biomni_run.py <workspace> <prompt_file> <cell_dir>

Drives Biomni's A1 agent on one BiomniBench-DA task with DeepSeek v4-pro (via
its OpenAI-compatible Custom source, for parity with every other backend), then
guarantees the two graded files exist in <workspace>:
  * If the agent wrote `trace.md` / `answer.txt` itself (its code tool can), keep
    those.
  * Otherwise synthesize them from A1.go()'s return `(log, final_content)` —
    `answer.txt` = final message, `trace.md` = the streamed step log — so a
    finished analysis is never scored 0 on a missing-file technicality.

Emits a one-line JSON summary (steps, chars) to stdout for the adapter.
"""
import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    workspace, prompt_file, cell_dir = (Path(sys.argv[1]), Path(sys.argv[2]),
                                        Path(sys.argv[3]))
    prompt = prompt_file.read_text(encoding="utf-8")

    base = (os.environ.get("DEEPSEEK_API_BASE")
            or os.environ.get("DEEPSEEK_BASE_URL"))
    key = os.environ.get("DEEPSEEK_API_KEY")
    model = os.environ.get("BIOMNI_MODEL", "deepseek-v4-pro")
    data_path = os.environ.get("BIOMNI_DATA_PATH",
                               "/scratch/users/steorra/env/biomni_data")

    # Biomni runs generated code in the process CWD; chdir into the staged
    # workspace so its code can read the task's data files and write outputs
    # back to the graded directory.
    os.chdir(workspace)

    from biomni.agent import A1

    started = time.monotonic()
    agent = A1(
        path=data_path, llm=model, source="Custom",
        base_url=base, api_key=key,
        expected_data_lake_files=[],       # skip the ~11GB data-lake download
        use_tool_retriever=True,           # biomni's designed capability
        timeout_seconds=int(os.environ.get("BIOMNI_TIMEOUT", "5400")),
    )

    err = None
    log, final = [], ""
    try:
        log, final = agent.go(prompt)
    except Exception as e:  # surface, don't swallow — still write fallbacks
        import traceback
        err = f"{type(e).__name__}: {e}"
        traceback.print_exc(file=sys.stderr)

    # Save the raw step log as biomni's trajectory (one JSON object per step),
    # so biomni has a raw event-stream record on disk like the other backends.
    try:
        with (cell_dir / "trajectory.jsonl").open("w", encoding="utf-8") as tf:
            for i, entry in enumerate(log or []):
                tf.write(json.dumps({"seq": i, "content": str(entry)},
                                    ensure_ascii=False) + "\n")
    except Exception:
        pass

    # Guarantee the graded files exist. Prefer whatever the agent wrote itself.
    ans = workspace / "answer.txt"
    trace = workspace / "trace.md"
    if not ans.is_file():
        ans.write_text((final or "").strip() + "\n", encoding="utf-8")
    if not trace.is_file():
        body = "\n\n".join(str(x) for x in (log or []))
        trace.write_text(
            "# Biomni analysis trace\n\n"
            "_Synthesized from the agent's streamed step log._\n\n" + body
            + "\n\n## Final answer\n\n" + (final or ""),
            encoding="utf-8",
        )

    print(json.dumps({
        "steps": len(log or []),
        "final_chars": len(final or ""),
        "elapsed_s": time.monotonic() - started,
        "error": err,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
