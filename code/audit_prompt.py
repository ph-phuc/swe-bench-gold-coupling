"""The auditor prompt: what Gemma 4 reads per task, and how its answer is parsed (card exp/cards/A1-gemma-auditor.md).

The materials are those the audit's first reader had (docs/w1-label-table-2026-10-27.md, "Method", step 2): the issue
and its hints, the gold patch, the SWE-ABS test patch with the tests wrong-but-passing runs fail (from the triage),
and agent patches that pass the original tests but fail SWE-ABS. The category definitions are the audit's own, word
for word. No verdict of either reader is shown. Stdlib only.
"""

from __future__ import annotations

import re

CATEGORIES = ("interface", "gold_choice", "in_scope", "env")
COUPLED = {"interface", "gold_choice"}

INSTRUCTIONS = """You are auditing one task from SWE-bench Verified. SWE-ABS is a hardened test suite: it adds tests to the \
original ones. Some agent patches pass the original tests but fail SWE-ABS, so SWE-ABS labels them wrong. Your job is \
to decide whether that label is fair.

Read the issue (and its hints), the reference ("gold") patch, the SWE-ABS test patch, the list of SWE-ABS tests that \
these agent patches fail, and the agent patches themselves. Then classify the most-failed SWE-ABS test into exactly \
one category:

- interface: needs a name, keyword or signature only gold adds. The label is false.
- gold_choice: asserts a design choice the issue leaves open or contradicts. The label is doubtful.
- in_scope: checks what the issue asks for or clearly implies. The label is genuine.
- env: an environment failure.

Judge against the issue and its hints, not against the gold patch: a test that only a fix written like gold can pass, \
for a reason the issue does not ask for, is not in_scope.

Answer with at most 150 words of reasoning, then one last line exactly of the form
VERDICT: <interface|gold_choice|in_scope|env>"""

TAIL = """Now classify the most-failed SWE-ABS test. At most 150 words of reasoning, then one last line exactly of the form
VERDICT: <interface|gold_choice|in_scope|env>"""

# Character caps per part (about 3.5 characters per token: the whole prompt stays near 8k tokens).
CAPS = {"issue": 5000, "hints": 2000, "gold": 5000, "abs_test": 6000, "patch": 3500}
N_PATCHES = 3

# "VERDICT\W*" takes ":", "**", "`" and the like; the lookahead skips an echoed template "<interface|gold_choice|...>".
_VERDICT = re.compile(r"VERDICT\W*(interface|gold[ _-]?choice|in[ _-]?scope|env(?:ironment)?)\b(?!\s*\|)",
                      re.IGNORECASE)


def clip(text: str, cap: int) -> str:
    text = (text or "").strip()
    if len(text) <= cap:
        return text
    return text[:cap] + f"\n[... {len(text) - cap} more characters cut ...]"


def render(p: dict) -> str:
    """The user message for one packet (see build_packets.packet for the fields)."""
    fails = "\n".join(f"- {t} (fails in {n} of {p['runs_read']} runs read)" for t, n in p["failing_tests"]) or "- (none)"
    errs = "\n".join(f"- {t}: {e}" for t, e in p["first_errors"]) or "- (none)"
    parts = [
        INSTRUCTIONS,
        f"## Task {p['instance_id']}",
        "### Issue\n```text\n" + clip(p["issue"], CAPS["issue"]) + "\n```",
        "### Hints\n```text\n" + (clip(p["hints"], CAPS["hints"]) or "(none)") + "\n```",
        "### Gold patch\n```diff\n" + clip(p["gold_patch"], CAPS["gold"]) + "\n```",
        "### SWE-ABS test patch\n```diff\n" + clip(p["abs_test_patch"], CAPS["abs_test"]) + "\n```",
        "### SWE-ABS tests the wrong-but-passing runs fail (most-failed first)\n" + fails,
        "### For each top test, one run that fails it, and that run's first error line (it may come from another "
        "test)\n" + errs,
    ]
    for i, a in enumerate(p["agent_patches"], 1):
        parts.append(f"### Agent patch {i} (passes the original tests, fails SWE-ABS)\n```diff\n"
                     + clip(a, CAPS["patch"]) + "\n```")
    parts.append(TAIL)
    return "\n\n".join(parts)


def parse(text: str) -> str | None:
    """The category on the last VERDICT line, or None."""
    hits = _VERDICT.findall(text or "")
    if not hits:
        return None
    v = re.sub(r"[ _-]+", "_", hits[-1].lower())
    return "env" if v.startswith("env") else v


def is_coupled(verdict: str | None) -> bool:
    """The audit's mapping (audit_tally.COUPLED): interface or gold_choice is coupled to gold. Anything else,
    including no verdict, is read as not coupled (card, "Primary")."""
    return verdict in COUPLED
