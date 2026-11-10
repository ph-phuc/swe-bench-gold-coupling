# Datasheet: SWE-bench gold-coupling census (v1.2.0)

Answers to the questions of *Datasheets for Datasets* (Gebru et al., arXiv:1803.09010), with the extra headings of
the Hugging Face dataset card template. Terms such as *judged*, *wbp* and *coupled* are defined in the
[Glossary](README.md#glossary) of the README. This file is the one place where the method and the limits are written;
the README points here.

## 1. Motivation

**Why was it made?** Hardened test suites such as SWE-ABS add tests to SWE-bench Verified so that patches which
pass weak tests are caught. Each new test is checked against one reference ("gold") fix, so a test can come to require
something only that fix does. This release asks one question of every SWE-ABS rejection: *does the issue, with its
hints, ask for what the failing test checks?* SWE-ABS's authors looked for this themselves and corrected 53 of 500
instances before publishing; this census applies one written standard to every rejection in the corrected release.

**Who made it?** Phuc Phan, for a writeup entered in the Kaggle *Gemma 4 Developer Agent Paper Track*.

## 2. Composition

| Unit | Count | File |
|---|---|---|
| Leaderboard entry (one system's resolved submission for one task), with three test labels | 39,133 (151 systems, 470 tasks, 31,654 unique patches) | `data/labels/entries.csv` |
| Task-level verdict on a task with at least one SWE-ABS rejection | 305 | `data/task_verdicts.csv` (view); records in `data/census/` |
| Refuter verdict on a coupled first verdict | 131 | `data/census/refute_*.jsonl` |
| Kind split of the coupled tasks | 108 (+ 22 refuter re-reads) | `data/census/split_*.jsonl` |
| Corrected per-system rate with bootstrap intervals | 151 systems (139 ranked) | `data/system_rates/` |
| Blind human spot check (letters only) | 10 tasks x 5 annotators | `data/spotcheck/` |
| Test-auditor benchmark (two-reader reference labels) | 85 tasks, 76 decided | `data/auditor_benchmark/` |
| Gemma 4 auditor outputs | E4B and 12B (fp16), 31B (nf4, exploratory); one greedy run each | `data/auditor_benchmark/predictions/` |
| Held-out auditor board (same reference labels, plus the no-model score's counts) | 220 tasks, 205 decided (64 coupled) | `data/auditor_benchmark/heldout/labels.jsonl` |
| Gemma 4 12B A2 outputs on the held-out board | 220 tasks, fp16, one greedy run | `data/auditor_benchmark/heldout/predictions/` |

- **Is it a sample?** No for the census: all 305 tasks with a SWE-ABS rejection were read. The entries are every
  prediction the SWE-bench Verified leaderboard marks resolved, as published in SWE-bench/experiments when collected.
  The spot check is 10 tasks; the kind-1 refuter check is a seeded 20% sample (19 of 97 calls re-read).
- **Labels.** `label_official`, `label_hardened`, `label_utboost`: `1` pass, `0` fail, empty = no valid verdict (the
  suite's gold or no-op control failed for that task, or the run gave no complete verdict).
- **What is not included.** Patch text, gold patches, full issue text and SWE-ABS test files. Entries carry a sha256 of
  the patch text, and `code/fetch_patches.py` fetches the patches from their public source so they can be joined back.
  Verdict records quote at most a sentence or two of an issue and name a test.
- **Splits.** None. This is an evaluation and audit resource, not a training set.
- **Personal or sensitive information.** None about people. System names are leaderboard submission names. The five
  spot-check annotators are anonymised as a1-a5 (a1 is the author).
- **Errors and noise.** Every verdict is a model judgement made per task on the most-failed hardened test; see
  [Limits](#limits). The README says how to report a label you think is wrong.

## 3. Collection process

- **Entries and labels.** Each entry was re-run on the original suite, SWE-ABS and UTBoost with the swebench 4.1
  harness in the task's Docker image. Every suite also ran gold and a no-op patch as controls; a suite whose controls
  fail is invalid for that task (447 tasks have all three suites valid, 23 have at least one invalid). SWE-ABS is graded
  with its own rule: every test in its log must pass.
- **Triage.** A script read from the logs which SWE-ABS tests the rejected runs fail, and named the most-failed one.
- **Readers and refuters.** Each verdict came from a fresh-context Claude Code subagent (`general-purpose`) running the
  model **`claude-opus-5-5`** at effort `high` (Claude Code 2.1.289). The rounds were 26 October 2026 (first round:
  near-total set and the 50-task random sample) and 29 October 2026 (census of the remaining 220 tasks). These values
  come from the session transcripts: every assistant message of the 7 + 20 reader agents and the 4 + 9 refuter agents
  carries `model: claude-opus-5-5` and `effort: high`. No model was passed explicitly, so the subagents ran on the
  session model. Temperature, top-p and the thinking budget are **not recorded**; extended thinking was on. The
  readers read the issue, hints, gold patch, the most-failed SWE-ABS test and two to five agent patches; they ran no
  code against the tasks. The prompts are in `briefs/`, verbatim except that a local path is removed.
- **Combination rule**, fixed before any refuter result was read: a task is `coupled` only when both the first reader
  and the refuter say `interface` or `gold_choice`. It is `contested` when the refuter disagrees, and it then counts in
  neither total.
- **The kind split** (3 November 2026): 6 reader and 2 refuter subagents, the same model, at effort `medium`, on
  `briefs/split_kind.md`. The 8 tasks both census readers called `interface` are kind 1 by rule.
- **Human spot check.** 10 tasks (6 kind 1, 2 kind 2, 2 in-scope controls), read blind by five annotators: a1 (the
  author) on a short packet without hints, a2-a5 on the full packet. The packets are not released because they quote
  issue and patch text.
- **Gemma 4 auditor.** `google/gemma-4-E4B-it`, `google/gemma-4-12B-it` and `google/gemma-4-31B-it` (nf4), at the
  Hugging Face revisions in `data/auditor_benchmark/configs/`. Greedy decoding, at most 600 new tokens, on Kaggle T4
  GPUs. The prompt and verdict parser are `code/audit_prompt.py`.
- **Held-out board.** The 220 census tasks outside the 85 first-round tasks, with the same two-reader reference
  (`coupled` / `genuine` / `contested` / `other`, equal task by task to `data/task_verdicts.csv`). Gemma 4 12B (fp16)
  ran once on them with a second prompt, A2 (test source, no gold patch, the question asked in parts), designed on the
  dev tasks and pre-registered before the held-out run; the A2 prompt itself is not in this release. Its outputs keep
  the parsed answer fields (one-sentence answers and a short issue quote) and the raw text. The no-model rule (top 20%
  by SWE-ABS rejection share) and the second-read combination were fixed after that run, so they are exploratory.

## 4. Preprocessing, cleaning, labelling

- Patches were hashed (sha256 of the patch text) and deduplicated for the unique-patch counts; no patch was edited.
- Verdict records are stored as the readers wrote them. `data/task_verdicts.csv` is a flat view built by
  `code/task_verdicts.py` from `data/census/` and can be rebuilt.
- `code/audit_tally.py --require-census` and `code/system_rates.py` exit non-zero when a count fails to reconcile
  across `entries.csv`, `per_task.csv`, `per_system.csv` and the census.

## 5. Uses

**Intended uses.**
- Re-scoring SWE-bench Verified systems under SWE-ABS with coupled tasks set aside, as a sensitivity range.
- Studying which hardened tests pin gold-specific behaviour, with the issue quote and test name as evidence.
- Benchmarking a test-auditor model on the 76 decided tasks of `data/auditor_benchmark/` (dev), and on the 205
  decided held-out tasks of `data/auditor_benchmark/heldout/` with `code/score_heldout.py` (Table 4, the board to
  beat). The census readers saw how many patches failed, so the no-model row and the reference labels are not
  independent.

**Out-of-scope uses.**
- Reading a `coupled` task as "every rejection on this task is a correct patch". The verdict is per task; many
  coupled tasks hold a genuinely wrong minority.
- Reading 8.7-10.8% as bounds on SWE-ABS's true error rate. It is a range under the per-task rule.
- Training on the verdicts as ground truth without a human check: they are model judgements from one model family.

## Limits

- **Per task, most-failed test.** The verdicts are per task, made on the most-failed hardened test. A coupled task can
  still hold genuinely wrong patches; we did no per-run read.
- **One model family, small human check.** The readers and the refuters are Claude models. The human check covers 10
  tasks; its five annotators agree with each other only moderately (Fleiss 0.36), and annotator a1 saw a shorter
  packet than a2-a5. The split's refuter re-read 22 of 108 tasks.
- **Lean of the `in_scope` rate.** `in_scope`-only rates lean low (coupling was looked for only on tasks with wbp). Read
  8.7-10.8% as a range under the per-task rule, not as bounds.
- **A grading-harness parser issue.** SWE-bench's Django log parser keys tests by docstring first line, so tests that
  share one can hide a failure: 15 runs in 2 Django tasks are confirmed wrongly "resolved" on the original suite, and
  up to 126 Django runs may be (`data/carried/`, not recomputed here).
- **Bootstrap determinism.** Intervals are deterministic for a fixed numpy (`default_rng(0)`; tested with numpy 2.5.2).
  Another numpy version may move interval bounds in the last digit; `reproduce.py` then reports the difference.

## 6. Distribution

- **Where.** GitHub repository https://github.com/ph-phuc/swe-bench-gold-coupling and Kaggle dataset `phucphan1406/swe-bench-gold-coupling-census` (title "SWE-bench gold-coupling census");
  the repository URL is also set in `CITATION.cff`.
- **Licences.** Code (`code/`, `reproduce.py`): MIT (`LICENSE`). Annotations and derived data (`data/`, `briefs/`,
  `draft_numbers.json`): CC BY 4.0 (`LICENSE-DATA`). Third-party excerpts stay under their own terms (`NOTICE`).
- **Third-party restrictions.** The leaderboard patches (SWE-bench/experiments) carry no licence file, which is why
  their text is not redistributed.

## 7. Maintenance

- **Who maintains it.** The author, through the repository's issue tracker.
- **Errata.** A reported wrong label is checked against its issue quote and test. A confirmed one is fixed in a new
  version: the record is corrected, the numbers are recomputed with `reproduce.py`, and the change is listed in
  `CHANGELOG.md`. Earlier versions stay available through their tags.
- **Versioning.** Semantic: a corrected label or recomputed number is a minor version; a change of schema is a major one.
- **Expected updates.** None planned beyond errata.
