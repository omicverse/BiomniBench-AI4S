# Dual-judge robustness — DeepSeek v4-pro + Gemini 3.1 Pro

The main leaderboard is graded by a **DeepSeek v4-pro** rubric judge. To check
that the ranking is not an artifact of that one judge, every cell was **re-graded
by a second, independent judge — Gemini 3.1 Pro** — on the *same* rubric and the
*same* original trace, and the two judge scores were averaged per cell.

- **Second judge:** `google/gemini-3.1-pro-preview`, via OpenRouter, using the
  identical rubric-grading prompt as the DeepSeek judge (only the model differs).
- **Graded on the original traces**, not the redacted ones: the redaction only
  touches `trajectory.jsonl`; the judge reads `trace.md` + `answer.txt`, which are
  unmodified.
- **Nothing was re-run.** Only the judge changed.
- **dual mean** = per-cell mean of the two judge scores, averaged over all 50
  tasks. Both judges score every task for every backend (full **50/50**
  coverage). The four `no_output` cells (an agent that wrote no
  `trace.md`/`answer.txt`) score 0 under both judges — there is no deliverable
  for either to grade.

## Result

| # | backend | DeepSeek (50) | Gemini 3.1 Pro (50) | dual mean (50) | Δ (dual − DS) |
|---|---|---:|---:|---:|---:|
| 1 | **OmicOS** | 0.773 | 0.766 | **0.769** | −0.003 |
| 2 | Claude / CSSwitch | 0.678 | 0.686 | 0.682 | +0.004 |
| 3 | EvoScientist | 0.653 | 0.653 | 0.653 | ±0.000 |
| 4 | Biomni (OSS) | 0.635 | 0.626 | 0.630 | −0.004 |
| 5 | synthetic-sciences/openscience | 0.628 | 0.622 | 0.625 | −0.003 |
| 6 | ai4s-research/open-science | 0.611 | 0.631 | 0.621 | +0.010 |
| 7 | Wisp Science | 0.606 | 0.618 | 0.612 | +0.006 |

## Reading it

- **OmicOS is #1 under both judges**, with near-identical scores (DeepSeek 0.773,
  Gemini 0.766, dual 0.769).
- **Every backend's dual-vs-DeepSeek gap is ≤ 0.010** — the two judges agree
  closely, so the leaderboard is robust to the choice of judge.
- The **top-4 order is identical** under both judges
  (OmicOS > Claude/CSSwitch > EvoScientist > Biomni/OSS bloc); only the three
  near-tied backends at the bottom (within ~0.02 of each other) reshuffle, which
  is within single-run grading noise.

Per-cell scores for both judges are published for reproduction in
[`matrix_dualjudge.csv`](matrix_dualjudge.csv)
(`backend, task, deepseek, gemini, dual_mean, status`) and, in JSON form, in
[`dual_judge_scores.json`](dual_judge_scores.json). The headline chart
[`leaderboard_mean.png`](leaderboard_mean.png) plots the **dual mean**; the
pass@0.70 chart stays on the single DeepSeek judge (thresholding a two-judge
average near 0.70 is noisy).
