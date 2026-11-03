# Changelog

All changes to the data, code and numbers of this release. A corrected label or a recomputed number gets a new minor
version; a change of schema gets a new major version. Each version is a git tag.

## 1.0.0 (2026-11-04)

First public version.

- 39,133 entry labels on the original suite, SWE-ABS and UTBoost (`data/labels/`).
- Verdicts on all 305 tasks with a SWE-ABS rejection: first reader, refuter on the 131 coupled first verdicts, and the
  kind split of the 108 coupled tasks (`data/census/`, `data/task_verdicts.csv`).
- Corrected per-system rates for 151 systems with task-bootstrap intervals (`data/system_rates/`), and Figure 1.
- Blind human spot check: letters of five annotators on 10 tasks (`data/spotcheck/`).
- Test-auditor benchmark (85 tasks, 76 decided) and Gemma 4 E4B, 12B and 31B-nf4 outputs (`data/auditor_benchmark/`).
- `reproduce.py`: 150 checks against the writeup's numbers.
