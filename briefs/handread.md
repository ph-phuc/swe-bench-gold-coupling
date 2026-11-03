# Hand-read brief: are SWE-ABS "wrong-but-passing" labels real?

> Release copy: verbatim from the run, except that the local working-copy path is replaced by `<ROOT>`.
> The `docs/`, `results/` and `data/w1/...` paths name files of the working copy, not of this release;
> README.md maps them to `data/` here.

The first-reader brief of the W1 label audit (`docs/w1-label-table-2026-10-27.md`, "Label audit"). Copied 29/10/2026
from the 26/10 session's scratchpad, where it was used for the near-total set, sample15 and sample35. The sample35
additions (the triage path, reading a passing patch, `in_scope_kind`) are folded in below, marked "(sample35)". The
29/10 census of the remaining 220 tasks uses this text unchanged, with only `<TRIAGE_FILE>`, `<OUT_FILE>` and the
task list filled in.

Context. We re-ran every SWE-bench Verified leaderboard patch that the leaderboard marks resolved on (a) the
original tests and (b) SWE-ABS hardened tests (extra tests written per task by the SWE-ABS authors). An entry is
"wrong-but-passing" (wbp) when it passes our re-run of the original tests but fails the SWE-ABS tests. Some tasks
have nearly every agent patch failing ABS. That can mean two different things:
- the agents' patches really are wrong or incomplete for what the issue asks (a genuine label), or
- the ABS test is coupled to the gold patch: it calls a name, keyword, signature or private helper that only the
  gold patch introduces, or asserts a design choice the issue does not ask for (a false label: a correct fix
  written differently fails).

Your job: for each task id given to you, decide which, from the files. Read only; do not edit any file except your
own output file.

## Files (all local, read-only)

Working copy root: `<ROOT>`
- Issue text and gold patch: `data/w1/server/suites/original.json` (a JSON list; fields `instance_id`,
  `problem_statement`, `patch` = gold patch, `hints_text`).
- ABS tests: `data/w1/server/suites/abs.json` (same layout; `test_patch` is the hardened test file diff).
- Agent patches: `data/w1/server/passing_patches/<iid>.jsonl` (one row per system: `system`, `sha`, `model_patch`).
- Triage of the failing ABS runs: `<TRIAGE_FILE>`, relative to the working copy root (sample35: under
  `results/w1_label_table/triage/`) (JSON list; per task `failing_tests` = [test, number of wbp runs failing it],
  `exceptions`, `sample` first error lines, `runs_read`).
- Per-task counts: `results/w1_label_table/per_task.csv` (`abs_wbp`, `abs_judged`).
- (sample35) Per-entry labels: `data/w1/work/label_long.csv`, columns system, instance_id, sha, label_official,
  label_hardened, label_utboost; official 1 + hardened 0 = wbp, 1 + 1 = passes ABS.

Use Python to load them (UTF-8). For each task: read the issue (and hints), the gold patch, the ABS test(s) that the
wbp runs fail most, the exceptions, and two or three agent patches (pick ones whose ABS run failed: their sha's
first 16 hex chars appear in the triage `sample` run names as `p_<sha16>`; otherwise any). Then classify.
(sample35) These tasks are not near-total, so many patches pass ABS too; read one patch that PASSES ABS when it
helps.

## Categories (pick one; use the most specific that fits the MOST-FAILED test)

- `interface`: the failing test needs a name, keyword argument, signature, attribute or private helper that only
  gold adds and the issue does not name (e.g. AttributeError/TypeError on a gold-only method or kwarg). False label.
- `gold_choice`: the test asserts behaviour the issue leaves open or contradicts (gold made a design choice; the
  issue proposes something else or is silent; e.g. issue suggests `except OSError`, test requires only
  BlockingIOError to be caught). Label is doubtful.
- `in_scope`: the test checks behaviour the issue asks for or clearly implies (an edge case of the requested fix),
  and the agents' patches really miss it. Genuine label.
- `env`: the failure comes from the environment or harness (database errors unrelated to the change, timeouts,
  warnings turned into errors, flaky), not from the patch. False label.
- `unclear`: you cannot tell from the files; say what is missing.

Be strict and concrete. Quote the issue (at most 25 words) and name the test. Do not guess at hidden context.

## Output

Write one JSON line per task to `<OUT_FILE>` with keys:
`instance_id`, `category`, `confidence` (high/medium/low), `top_test`, `issue_quote`, `test_requires` (one
sentence), `agents_do` (one sentence: what the agent patches you read did instead), `why` (one or two sentences).
(sample35) Add one extra key per line: `in_scope_kind` = "miss" (the patch misses what the issue asks),
"regression" (an extra change breaks existing behaviour) or null when the category is not in_scope.
Then reply with a compact table: instance_id, category, confidence, one-line why.

Read-only except your output file; no git, no server, no web. Low memory machine: load JSON once per Python
process, no background loops.
