# Split brief: which kind of "coupled" is this task? (gold artefact vs gold improvement)

> Release copy: verbatim from the run, except that the local working-copy path is replaced by `<ROOT>`, the annotator's name by "the author", and a pointer to an internal planning note is removed.
> The `docs/`, `results/` and `data/w1/...` paths name files of the working copy, not of this release;
> README.md maps them to `data/` here.

Written 03/11/2026 for the gold_choice split (`docs/gold-choice-split-2026-11-03.md`).
The census (`docs/w1-label-table-2026-10-27.md`) calls 108 tasks `coupled`: two readers agreed that the SWE-ABS test
the wrong-but-passing (wbp) runs fail most is coupled to the gold patch (`interface` or `gold_choice`). The author's spot
check (`docs/w1-spotcheck-result-2026-11-03.md`) disagreed on two of them, both where gold *improved on* the fix the
issue itself proposed. This brief splits the coupled tasks into two kinds. It does not re-open whether a task is
coupled; take that as given.

## The kinds (decide for the MOST-FAILED ABS test of the task)

**Kind 1, "gold artefact".** The test pins something a correct fix need not do:
- an accident of gold (e.g. a crash or message that only gold's particular split or code path produces);
- an exact output form, wording or term order;
- a gold-only internal name, signature, keyword or helper (every `interface` case is kind 1);
- a side change of gold outside what the issue and hints ask (gold also changed X; the test checks X);
- or a gold design choice on a point where the issue and hints are silent or open.

**Kind 2, "gold improvement".** All three must hold, each with evidence:
- (a) the issue or the hints propose a **concrete** fix (code, or a specific behaviour such as "catch OSError and
  return False"); quote it;
- (b) the wbp agents implemented **that** proposal (from the agent patches or the census row's `agents_do`);
- (c) gold deliberately does something narrower or better than the proposal, the most-failed test checks exactly
  that difference, and a careful maintainer could reject the issue's proposal **on its merits** (it is wrong,
  unsafe, or too broad, not merely different).

If any conjunct fails, it is not kind 2. In particular: proposal present but the test pins a side change or a form
detail = kind 1; issue silent on the pinned behaviour = kind 1, however sensible gold's choice is; gold merely
differs from the proposal without being defensibly better = kind 1.

**unclear.** You cannot decide from the bundle (say what is missing).

Examples (from the spot check; they are the reason for this brief, so do not treat them as independent evidence):
- django__django-13410, kind 2: the issue proposes `except OSError: return False`; agents copy it; gold narrows to
  `BlockingIOError`; the test requires other OSErrors to propagate. Swallowing every OSError is defensibly wrong.
- django__django-16527, kind 2: the issue's fix keeps `has_change_permission` (hints agree); gold drops it; the test
  asks an add+view user to see "Save as new". Save-as-new is an add, so the drop is defensible.
- Kind 1 shapes: a test that asserts an exact repr string or term order; a test that fails with AttributeError on a
  helper only gold adds; a test of a second code path gold also touched though the issue names only the first.

## Input

Each task has one bundle: `<BUNDLE_DIR>/<instance_id>.md` with the issue, hints, full gold patch, full ABS test
patch, triage counts (`failing_tests` = [test, wbp runs failing it]; the first one is the most-failed), first error
lines, the census readers' rows, and up to three agent patches whose ABS run failed. Big bundles: use Grep or Read
with offset/limit (a plain Read over ~25k tokens fails). Read only; write only your output file.

## Output

One JSON line per task to `<OUT_FILE>`:
`instance_id`, `kind` (1, 2 or "unclear"), `confidence` (high/medium/low), `top_test`, `evidence` (a quote of at
most 30 words from the issue or hints: for kind 2 the proposal; for kind 1 the part that shows the issue does not ask
for what the test pins, or "" if the issue is silent), `proposal_in_issue` (true/false: does the issue or hints
propose a concrete fix?), `agents_follow_proposal` (true/false/null), `why` (one sentence).

Then reply with a compact table: instance_id, kind, confidence, one-line why.

## Refuter variant (second pass)

You get tasks a first reader has already split, with their call in `<FIRST_FILE>`. Form your own view from the
bundle first, then read the first call and try to break it:
- for a kind-2 call, pick the weakest of (a), (b), (c) and argue it fails (is the "proposal" really concrete? did
  the agents really follow it, or something else? is the pinned behaviour really the proposal's flaw, or a side
  detail? could a maintainer really reject the proposal on its merits?);
- for a kind-1 call, argue it is kind 2: find a concrete proposal in the issue or hints that the agents followed
  and that gold defensibly improved on in exactly what the test checks.

Write one JSON line per task to `<OUT_FILE>`: `instance_id`, `first_kind`, `your_kind` (1, 2, "unclear"), `agree`
(true/false), `reason` (one or two sentences, quote the issue or hints if it decides it).
