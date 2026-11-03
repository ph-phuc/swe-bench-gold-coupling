"""Tally of the W1 label audit (docs/w1-label-table-2026-10-27.md, "Label audit"), from results/w1_label_table/ only.

    python code/audit_tally.py [--dir data/census] [--require-census]

(Release copy: only the default --dir differs from the run's code.)

Sets: CENSUS_SETS (the 27/10 near-total and sample sets, plus the 29/10 census of the rest when present); refuter
verdicts from REFUTE_FILES. `census` sums every set against all tasks with wbp; --require-census exits 1 while a task
with wbp is unread or a coupled first verdict has no refuter verdict.

A hand-read task is `coupled` when the first reader says interface or gold_choice AND the refuter agrees (either
category); `contested` when the refuter says otherwise; `coupled_unrefuted` when no refuter verdict exists yet.
Other first-reader categories are kept as they are. Per set: tasks, ABS wbp entries and unique wbp patches by class,
joined with per_task.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

COUPLED = {"interface", "gold_choice"}
ALLOWED = COUPLED | {"in_scope", "env", "unclear"}
SETS = ("handread_near_total.jsonl", "handread_sample15.jsonl", "handread_sample35.jsonl")
# The 29/10 census of the other 220 tasks with wbp (same briefs, code/w1_gate/briefs/). Kept out of SETS on purpose:
# build_data.py reads SETS, and the closed W1 gate's data must still rebuild byte for byte.
CENSUS_SETS = SETS + ("handread_rest.jsonl",)
REFUTE_FILES = ("refute_round.jsonl", "refute_rest.jsonl")
KINDS = {"miss", "regression", None}


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def classify(first: str, refuter: str | None) -> str:
    if first not in COUPLED:
        return first
    if refuter is None:
        return "coupled_unrefuted"
    return "coupled" if refuter in COUPLED else "contested"


def unique_rows(rows: list[dict], key: str, name: str) -> list[dict]:
    """Rows with a valid `key` value and no repeated instance_id (a repeat or a typo would change a count silently)."""
    ids = [r["instance_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise SystemExit(f"{name}: repeated instance_id")
    bad = [r["instance_id"] for r in rows if r.get(key) not in ALLOWED]
    if bad:
        raise SystemExit(f"{name}: {key} not in {sorted(ALLOWED)} for {bad}")
    return rows


def refuter_verdicts(d: Path) -> dict[str, str]:
    """instance_id -> refuter verdict over REFUTE_FILES (absent files skipped); a task refuted in two files is an error."""
    ref: dict[str, str] = {}
    for name in REFUTE_FILES:
        if not (d / name).is_file():
            continue
        for r in unique_rows(read_jsonl(d / name), "your_verdict", name):
            if r["instance_id"] in ref:
                raise SystemExit(f"{r['instance_id']} has a refuter verdict in two files")
            ref[r["instance_id"]] = r["your_verdict"]
    return ref


def tally(d: Path) -> dict:
    with open(d / "per_task.csv", encoding="utf-8") as fh:
        tasks = {t["instance_id"]: t for t in csv.DictReader(fh)}
    ref = refuter_verdicts(d)
    out = {}
    seen: dict[str, str] = {}
    all_n, all_ent, all_uq = Counter(), Counter(), Counter()
    for name in CENSUS_SETS:
        if not (d / name).is_file():
            continue
        n, ent, uq, contested = Counter(), Counter(), Counter(), []
        for r in unique_rows(read_jsonl(d / name), "category", name):
            iid = r["instance_id"]
            if iid in seen:
                raise SystemExit(f"{iid} is in {seen[iid]} and {name}")
            if iid not in tasks:
                raise SystemExit(f"{name}: {iid} is not in per_task.csv")
            if name == "handread_rest.jsonl" and "in_scope_kind" not in r:
                raise SystemExit(f"{name}: {iid} has no in_scope_kind")
            if "in_scope_kind" in r and (r["in_scope_kind"] not in KINDS
                                         or (r["in_scope_kind"] is None) != (r["category"] != "in_scope")):
                raise SystemExit(f"{name}: {iid} has in_scope_kind {r['in_scope_kind']!r} with {r['category']}")
            seen[iid] = name
            k = classify(r["category"], ref.get(iid))
            n[k] += 1
            ent[k] += int(tasks[iid]["abs_wbp"])
            uq[k] += int(tasks[iid]["unique_abs_wbp"])
            if k == "contested":
                contested.append([iid, ref[iid]])
        out[name] = {"tasks": dict(n), "abs_wbp": dict(ent), "unique_abs_wbp": dict(uq),
                     "abs_wbp_total": sum(ent.values()), "contested": contested}
        all_n.update(n), all_ent.update(ent), all_uq.update(uq)
    stray = sorted(set(ref) - set(seen))
    if stray:
        raise SystemExit(f"refuter verdicts for tasks no set holds: {stray}")
    out["refuter"] = {"verdicts": len(ref), "upheld": sum(v in COUPLED for v in ref.values())}
    with_wbp = {i for i, t in tasks.items() if int(t["abs_wbp"]) > 0}
    total = sum(int(tasks[i]["abs_wbp"]) for i in with_wbp)
    unread = sorted(with_wbp - set(seen))
    # A share of all wbp entries means something only once every task is read; before that, read-only entries over
    # the full total would understate it (headline_share.py estimates it from the sample instead).
    out["census"] = {"tasks_with_wbp": len(with_wbp), "read": len(set(seen) & with_wbp),
                     "unread": unread, "tasks": dict(all_n), "abs_wbp": dict(all_ent),
                     "unique_abs_wbp": dict(all_uq), "abs_wbp_total": total,
                     "abs_wbp_share": {k: round(v / total, 4) for k, v in all_ent.items()}
                     if total and not unread else None}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("data/census"))
    ap.add_argument("--require-census", action="store_true",
                    help="exit 1 unless every task with wbp is read and every coupled first verdict is refuted")
    a = ap.parse_args(argv)
    out = tally(a.dir)
    print(json.dumps(out, indent=1))
    if a.require_census:
        c = out["census"]
        if c["unread"] or c["tasks"].get("coupled_unrefuted"):
            print(f"census incomplete: {len(c['unread'])} unread, {c['tasks'].get('coupled_unrefuted', 0)} "
                  "coupled verdicts without a refuter", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
