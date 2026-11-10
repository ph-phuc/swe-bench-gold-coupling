# Changelog

All changes to the data, code and numbers of this release. A corrected label or a recomputed number gets a new minor
version; a change of schema gets a new major version. Each version is a git tag.

## 1.1.0 (2026-11-10)

Closes the reproduction gap for the numbers the writeup added after 04/11. No label, verdict or schema changes.

- `data/carried/b1_tally.json`: the B1 re-run — the most-failed test cut from the file on 30 tasks (28 valid). Adds
  three checks: 68.5% of entries pass every other hardened test with tests failing on the same entries set aside,
  53.3% with only the named test removed, 1,676 valid runs.
- `data/carried/a4_eval.json`: the A4 pre-registered run (Gemma 4 12B writes one test from the issue). Adds three
  checks: valid on 68 of 205 held-out tasks (below the 40% floor), kappa 0.04 on those 68.
- `reproduce.py` reads nested keys and an optional `scale`, so carried numbers can be quoted as percentages;
  **156 checks**, all passing.
- `README.md`, `DATASHEET.md`: version 1.1.0 and the new check count.
- `notebooks/reproduce_and_audit.ipynb` (10/11): its pass check and text said 150; now 156. `CITATION.cff`: 1.1.0.

## 1.0.0 (2026-11-04)

First public version.

- 39,133 entry labels on the original suite, SWE-ABS and UTBoost (`data/labels/`).
- Verdicts on all 305 tasks with a SWE-ABS rejection: first reader, refuter on the 131 coupled first verdicts, and the
  kind split of the 108 coupled tasks (`data/census/`, `data/task_verdicts.csv`).
- Corrected per-system rates for 151 systems with task-bootstrap intervals (`data/system_rates/`), and Figure 1.
- Blind human spot check: letters of five annotators on 10 tasks (`data/spotcheck/`).
- Test-auditor benchmark (85 tasks, 76 decided) and Gemma 4 E4B, 12B and 31B-nf4 outputs (`data/auditor_benchmark/`).
- `reproduce.py`: 150 checks against the writeup's numbers.
