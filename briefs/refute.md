# Refuter brief: challenge "the hardened test is coupled to gold" verdicts

> Release copy: verbatim from the run, except that the local working-copy path is replaced by `<ROOT>`.
> The `docs/`, `results/` and `data/w1/...` paths name files of the working copy, not of this release;
> README.md maps them to `data/` here.

The refuter brief of the W1 label audit (`docs/w1-label-table-2026-10-27.md`, "Label audit"). Copied 29/10/2026 from
the 26/10 session's scratchpad. The 26/10 launches filled in `<VERDICTS_FILE>`, `<OUT_FILE>`, the triage file and
the task list, and for non-near-total tasks pointed to the per-entry labels (marked "(non-near-total)" below). The
29/10 census of the remaining 220 tasks uses this text unchanged with those slots filled.

A first reader classified SWE-ABS wrong-but-passing labels on some SWE-bench Verified tasks as false or doubtful
(`interface` or `gold_choice`): the ABS test is said to require a gold-only name/signature, or a design choice the
issue does not ask for, so agent patches that fail it are not really wrong. These verdicts would go into a paper as
"SWE-ABS's hardened labels are partly gold-coupled". Your job is to try to REFUTE each verdict, independently.

For each task id given to you, read (Python, UTF-8, read-only):
- working copy root `<ROOT>`
- issue + hints + gold patch: `data/w1/server/suites/original.json` (`problem_statement`, `hints_text`, `patch`)
- ABS tests: `data/w1/server/suites/abs.json` (`test_patch`)
- agent patches: `data/w1/server/passing_patches/<iid>.jsonl`
- failing tests per task: `<TRIAGE_FILE>` (`failing_tests`, `sample` with run names `p_<sha16>`)
- the first reader's verdict: `<VERDICTS_FILE>` (one JSON line per task)
- (non-near-total) per-entry labels in `data/w1/work/label_long.csv` (official 1 + hardened 0 = wbp; 1 + 1 = passes
  ABS) if a passing patch helps.

Ask: would a careful maintainer reviewing the agent patch against the issue (and hints) reject it for the reason
the ABS test encodes? If yes, the label is genuine (`in_scope`) and the first verdict is refuted. If the test
needs a gold-only name, signature or choice that the issue and hints do not imply, the verdict stands.
Do not read the first reader's reasoning until you have formed your own view from the files.

Write one JSON line per task to `<OUT_FILE>`: `instance_id`, `first_verdict`, `your_verdict`
(interface / gold_choice / in_scope / env / unclear), `agree` (true/false), `reason` (one or two sentences, quote
the issue or hint if it decides it). Reply with a compact table and the agreement count.

Read-only except your output file; no git, no server, no web. Low-memory machine: load JSON once per Python
process, no background loops.
