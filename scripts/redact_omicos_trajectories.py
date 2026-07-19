#!/usr/bin/env python
"""Redact proprietary agent/skill CONTENT from the omicos trajectories.

OmicOS's agent and skill *definitions* (the `omicos-admin` catalog) are private.
The omicos runs invoke them, so the raw `trajectory.jsonl` embeds their bodies
via tool outputs. This script strips only that proprietary CONTENT, replacing it
with a short notice, while keeping everything needed to follow the run:

  KEPT   agent/skill NAMES, the tool-call structure (which skills/agents were
         used), `registry_lookup` output (public OmicVerse API), and ALL the
         analysis (every `run_python_code` step, its outputs, the results).
  WITHHELD  the bodies only —
         - `skill` output       → the loaded SKILL.md text
         - `agent_select` output → the agent catalog (descriptions + skill lists)
         - `skill_resource` output → skill reference docs / asset scripts
         - `call_agent` handoff framing (the "you are the selected specialist…" arg)
         - any `run_python_code` that embeds a proprietary asset's source verbatim

Idempotent. Run over trajectories/omicos/ before publishing.
"""
import json
import sys
from pathlib import Path

NOTICE = ("[Withheld under OmicOS's privacy policy — the associated agent/skill "
          "definition and resources are not disclosed.]")

# Substantial proprietary bodies that sometimes get pasted into executed code.
EMBEDDED_BODY_MARKERS = [
    "def make_html_report", "base64-embedded", "源境解码", "PrimorDecode",
    "## Why (the real failure", "Use this contract for every analysis figure",
    "# Cross-platform publication font resolution",
    "# OmicVerse Visualization Contract",
]


def redact_file(fp: Path) -> int:
    n = 0
    out = []
    for ln in fp.read_text().splitlines():
        try:
            o = json.loads(ln)
        except Exception:
            out.append(ln)
            continue
        c = o.get("content")
        if isinstance(c, dict):
            for tc in c.get("tool_calls", []):
                name = tc.get("name")
                oo = str(tc.get("output", ""))
                if name == "skill" and ("Loaded skill" in oo or oo == NOTICE):
                    if tc.get("output") != NOTICE:
                        tc["output"] = NOTICE; n += 1
                elif name == "agent_select":
                    if tc.get("output") != NOTICE:
                        tc["output"] = NOTICE; n += 1
                elif name == "skill_resource" and oo.strip():
                    if tc.get("output") != NOTICE:
                        tc["output"] = NOTICE; n += 1
                elif name == "call_agent":
                    a = tc.get("arguments")
                    if isinstance(a, str) and "selected specialist" in a:
                        tc["arguments"] = NOTICE; n += 1
                elif name == "run_python_code":
                    a = str(tc.get("arguments", ""))
                    if any(m in a for m in EMBEDDED_BODY_MARKERS):
                        tc["arguments"] = NOTICE; n += 1
                    if any(m in oo for m in EMBEDDED_BODY_MARKERS):
                        tc["output"] = NOTICE; n += 1
        out.append(json.dumps(o, ensure_ascii=False))
    fp.write_text("\n".join(out) + "\n")
    return n


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path(__file__).resolve().parents[1] / "trajectories" / "omicos"
    total = files = 0
    for fp in sorted(root.glob("*/trajectory.jsonl")):
        total += redact_file(fp); files += 1
    print(f"redacted {total} proprietary blocks across {files} omicos trajectories")


if __name__ == "__main__":
    main()
