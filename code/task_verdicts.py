"""One row per task with SWE-ABS wrong-but-passing entries (305): the first reader's verdict record, the refuter's
verdict, the combined class and the task's counts. A convenience view built only from data/census/.

    python code/task_verdicts.py [--dir data/census] [--out data/task_verdicts.csv]

`class` is audit_tally.classify(first category, refuter verdict): coupled, contested, in_scope or env.
`kind` splits the coupled tasks: 1 (the test pins a gold artefact) or 2 (it checks a gold improvement over the
issue's own proposed fix), from split_tally.json (code/split_tally.py); empty for tasks that are not coupled.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_tally import CENSUS_SETS, REFUTE_FILES, classify, read_jsonl  # noqa: E402

FIELDS = ["instance_id", "read_set", "class", "kind", "first_category", "confidence", "top_test", "issue_quote",
          "test_requires", "agents_do", "why", "in_scope_kind", "refuter_verdict", "refuter_reason",
          "abs_wbp", "abs_judged", "unique_abs_wbp"]


def build(d: Path) -> str:
    with open(d / "per_task.csv", encoding="utf-8") as fh:
        tasks = {t["instance_id"]: t for t in csv.DictReader(fh)}
    ref = {}
    for name in REFUTE_FILES:
        for r in read_jsonl(d / name):
            ref[r["instance_id"]] = r
    split = json.loads((d / "split_tally.json").read_text(encoding="utf-8"))["task_ids"]
    kind_of = {i: "1" for i in split["kind1"]} | {i: "2" for i in split["kind2"]}
    if any(split[k] for k in split if k not in ("kind1", "kind2")):
        raise SystemExit("split_tally.json has contested or unclear kinds; task_verdicts.py does not handle them")
    rows = []
    for name in CENSUS_SETS:
        for r in read_jsonl(d / name):
            iid = r["instance_id"]
            rf = ref.get(iid, {})
            t = tasks[iid]
            rows.append({
                "instance_id": iid, "read_set": name.removeprefix("handread_").removesuffix(".jsonl"),
                "class": classify(r["category"], rf.get("your_verdict")), "kind": kind_of.get(iid, ""),
                "first_category": r["category"], "confidence": r.get("confidence", ""),
                "top_test": r.get("top_test", ""), "issue_quote": r.get("issue_quote", ""),
                "test_requires": r.get("test_requires", ""), "agents_do": r.get("agents_do", ""),
                "why": r.get("why", ""), "in_scope_kind": r.get("in_scope_kind") or "",
                "refuter_verdict": rf.get("your_verdict", ""), "refuter_reason": rf.get("reason", ""),
                "abs_wbp": t["abs_wbp"], "abs_judged": t["abs_judged"], "unique_abs_wbp": t["unique_abs_wbp"]})
    rows.sort(key=lambda x: x["instance_id"])
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("data/census"))
    ap.add_argument("--out", type=Path, default=Path("data/task_verdicts.csv"))
    a = ap.parse_args(argv)
    a.out.write_text(build(a.dir), encoding="utf-8", newline="")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
