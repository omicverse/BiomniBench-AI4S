"""The user message sent to every agent.

BiomniBench's judge reads two files the agent must create in its working dir:
`trace.md` (structured analytical trace) and `answer.txt` (plain final answer).
The task instruction itself already specifies the required `trace.md` sections,
so we pass it verbatim and wrap it with the load-bearing OUTPUT CONTRACT.

Two flavors:
  * ``generic`` — the neutral contract sent to any third-party agent
    (EvoScientist, imported desktop artifacts). No omicos-specific tool names.
  * ``omicos``  — the generic contract PLUS the multi-specialist `call_agent`
    orchestration paragraph that the omicos `vertical_agent_selector` relies on
    (lifted from omicos-biomnibench/matrix.py so omicos behaves identically here).

The task text + rubric are identical across flavors; only the closing
agent-operating notes differ. This deviation is logged in
docs/parity-caveats.md.
"""

from __future__ import annotations

_CORE = (
    "You are completing ONE task from the BiomniBench-DA benchmark. "
    "The data files for this task are already present in your current "
    "working directory; the task brief is also in this directory as "
    "`instruction.md`. Use your tools to inspect the data, run any "
    "code or notebooks you need, and complete every part of the task.\n\n"
    "TASK INSTRUCTION (verbatim from the dataset):\n"
    "----------\n"
    "{instruction}\n"
    "----------\n\n"
    "OUTPUT CONTRACT (load-bearing — the judge reads these files):\n"
    "- Write your structured analytical trace to `trace.md` in this "
    "working directory. The instruction above specifies the required "
    "sections (Objective, Data Sources, Approach with code, Results, "
    "References) and the expected level of detail; follow them.\n"
    "- Write your plain-text final answer to `answer.txt` in this "
    "working directory.\n"
    "- The dataset's instruction may mention paths like `/app/trace.md`; "
    "ignore the `/app/` prefix — write to the current working directory "
    "instead. The grader looks for `./trace.md` and `./answer.txt`.\n\n"
    "Operating constraints:\n"
    "- All evidence must come from files in this workspace; do not guess "
    "from prior knowledge alone. Do NOT search for the source paper, "
    "figures, or supplementary materials (see instruction).\n"
    "- This is a non-interactive benchmark run — there is no human "
    "reviewer to approve a plan. Execute directly. Never end your turn "
    "waiting on a plan approval: if a plan/approval tool is ever "
    "invoked, treat it as auto-approved and keep executing immediately "
    "(nobody will ever approve it, so waiting = a zero).\n"
    "- After writing `trace.md` and `answer.txt`, verify both files exist "
    "before ending your turn. A missing file scores 0.\n"
)

_OMICOS_ORCHESTRATION = (
    "\nMulti-specialist orchestration:\n"
    "BiomniBench tasks span multiple phases — data wrangling, statistical "
    "analysis, biological interpretation, translational implications, "
    "polished narrative. Your `## Available agents` roster lists sibling "
    "specialists; you can `call_agent` to delegate phases that fall outside "
    "your own specialty. Two natural handoffs the rubric rewards:\n\n"
    "  * `clinical_translator_pro` — for the 'biological / clinical "
    "interpretation' and 'translational implications' content. Hand it your "
    "concrete findings (gene lists, enriched populations, statistics) and ask "
    "for the mechanistic / translational paragraph.\n"
    "  * `scientific_writer` — for figure-quality narrative on the "
    "Results / Discussion sections.\n\n"
    "Use delegation when it strictly improves the deliverable; don't delegate "
    "steps you can complete competently yourself. After the sub-agent returns "
    "its text, merge it into `trace.md` under the appropriate section (the "
    "file you write is what the judge sees, not the sub-agent's reply text). "
    "The runtime caps delegation depth at 6 and refuses cycles — you can chain "
    "handoffs safely.\n"
    "- Do NOT use plan mode (`plan__enter` / `plan__write` / "
    "`plan__request_approval`)."
)


def build_prompt(instruction: str, *, flavor: str = "generic") -> str:
    """Render the user message for one task.

    ``flavor="omicos"`` appends the ``call_agent`` orchestration paragraph the
    omicos selector agent expects; any other value yields the neutral prompt.
    """

    msg = _CORE.format(instruction=instruction)
    if flavor == "omicos":
        msg += _OMICOS_ORCHESTRATION
    return msg
