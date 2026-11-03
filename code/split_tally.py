"""Tally of the gold_choice split (docs/gold-choice-split-2026-11-03.md), from data/census/ only.
(Release copy: only the default --dir and two comments differ from the run's code.)

    python code/split_tally.py                 # tally -> data/census/split_tally.json
    python code/split_tally.py --sample        # print the kind-1 ids the refuter re-reads (seeded 20%)
    python code/split_tally.py --merge <dir>   # build split_kind.jsonl from reader parts first*.jsonl

Inputs: the census's coupled tasks (audit_tally.classify), `split_kind.jsonl` (one row per coupled task: `kind` 1, 2
or "unclear"; `reader` "rule" for the tasks both census readers called `interface`, which are kind 1 by the brief,
"model" otherwise) and `split_refute.jsonl` (refuter rows: `first_kind`, `your_kind`, `agree`).

Final class per task:
- kind2: first reader 2 and refuter 2.  kind2_contested: first reader 2, refuter anything else.
- kind1: first reader (or rule) 1, and the refuter, when it re-read the task, also 1.
- kind1_contested: first reader 1, a refuter re-read it and said anything else.
- unclear: first reader "unclear".
Every first-reader kind-2 call and every task in the seeded 20% sample of model-read kind-1 calls must have a
refuter row; a refuter row for any other task is an error.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

import audit_tally as at

KINDS = {1, 2, "unclear"}
SEED = 20261103
SAMPLE_FRAC = 0.2
# Known from the human spot check (docs/w1-spotcheck-result-2026-11-03.md): G on 13410 and 16527 (gold improved on the
# issue's proposal), C on the others. A sanity check, not validation: 13410/16527 are the brief's own examples and
# 25973 is interface/interface (kind 1 by rule).
SANITY = {"django__django-13410": "kind2", "django__django-16527": "kind2", "django__django-13112": "kind1",
          "sympy__sympy-11618": "kind1", "django__django-11276": "kind1",
          "scikit-learn__scikit-learn-25973": "kind1"}
CLASSES = ("kind1", "kind1_contested", "kind2", "kind2_contested", "unclear")


def coupled(d: Path) -> dict[str, dict]:
    """instance_id -> {first, refuter, abs_wbp} for the census's coupled tasks."""
    ref = at.refuter_verdicts(d)
    with open(d / "per_task.csv", encoding="utf-8") as fh:
        wbp = {t["instance_id"]: int(t["abs_wbp"]) for t in csv.DictReader(fh)}
    out = {}
    for name in at.CENSUS_SETS:
        if not (d / name).is_file():
            continue
        for r in at.read_jsonl(d / name):
            iid = r["instance_id"]
            if at.classify(r["category"], ref.get(iid)) == "coupled":
                out[iid] = {"first": r["category"], "refuter": ref[iid], "abs_wbp": wbp[iid]}
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return (max(0.0, mid - half), min(1.0, mid + half))


def by_rule(c: dict) -> bool:
    return c["first"] == "interface" and c["refuter"] == "interface"


def rows_by_id(rows: list[dict], key: str, name: str) -> dict[str, dict]:
    out = {}
    for r in rows:
        if r["instance_id"] in out:
            raise SystemExit(f"{name}: repeated instance_id {r['instance_id']}")
        v = r.get(key)
        if not ((type(v) is int and v in {1, 2}) or v == "unclear"):
            raise SystemExit(f"{name}: {key}={r.get(key)!r} for {r['instance_id']}")
        out[r["instance_id"]] = r
    return out


def refute_sample(split: dict[str, dict]) -> list[str]:
    """The seeded 20% of model-read kind-1 calls (rule rows are not reader calls)."""
    pool = sorted(i for i, r in split.items() if r["kind"] == 1 and r.get("reader") == "model")
    n = round(SAMPLE_FRAC * len(pool))
    return sorted(random.Random(SEED).sample(pool, n))


def final_class(first: int | str, refuted: dict | None) -> str:
    if first == "unclear":
        return "unclear"
    if first == 2:
        return "kind2" if refuted and refuted["your_kind"] == 2 else "kind2_contested"
    if refuted is None or refuted["your_kind"] == 1:
        return "kind1"
    return "kind1_contested"


def tally(d: Path) -> dict:
    cp = coupled(d)
    split = rows_by_id(at.read_jsonl(d / "split_kind.jsonl"), "kind", "split_kind.jsonl")
    if set(split) != set(cp):
        raise SystemExit(f"split_kind.jsonl covers {len(split)} tasks; coupled tasks {len(cp)}; "
                         f"missing {sorted(set(cp) - set(split))}, extra {sorted(set(split) - set(cp))}")
    for iid, r in split.items():
        if (r.get("reader") == "rule") != by_rule(cp[iid]) or r.get("reader") not in {"rule", "model"}:
            raise SystemExit(f"{iid}: reader {r.get('reader')!r} does not match the interface rule")
        if r["reader"] == "rule" and r["kind"] != 1:
            raise SystemExit(f"{iid}: a rule row must be kind 1")
    rp = d / "split_refute.jsonl"
    refute = rows_by_id(at.read_jsonl(rp), "your_kind", rp.name) if rp.is_file() else {}
    sample = refute_sample(split)
    need = sorted({i for i, r in split.items() if r["kind"] == 2} | set(sample))
    missing = sorted(set(need) - set(refute))
    stray = sorted(set(refute) - set(need))
    if stray:
        raise SystemExit(f"refuter rows for tasks outside the kind-2 calls and the sample: {stray}")
    for iid, r in refute.items():
        if r.get("first_kind") != split[iid]["kind"]:
            raise SystemExit(f"{iid}: refuter first_kind {r.get('first_kind')!r} != split kind {split[iid]['kind']!r}")
        if r.get("agree") != (r["your_kind"] == r["first_kind"]):
            raise SystemExit(f"{iid}: refuter agree={r.get('agree')!r} does not match its kinds")
    cls = {i: final_class(split[i]["kind"], refute.get(i)) for i in split}
    n, ent = Counter(cls.values()), Counter()
    for i, k in cls.items():
        ent[k] += cp[i]["abs_wbp"]
    census = at.tally(d)["census"]
    if census["abs_wbp_share"] is None or census["tasks"].get("coupled_unrefuted"):
        raise SystemExit("census incomplete: shares of all wbp would be wrong")
    total, coupled_total = census["abs_wbp_total"], sum(c["abs_wbp"] for c in cp.values())
    if coupled_total != census["abs_wbp"].get("coupled"):
        raise SystemExit("coupled entries do not match audit_tally's census")
    refuted_k2 = [i for i in refute if split[i]["kind"] == 2]
    refuted_k1 = [i for i in refute if split[i]["kind"] == 1]
    k1_up = sum(refute[i]["your_kind"] == 1 for i in refuted_k1)
    # Sensitivity: kind-1 tasks the first reader marked medium/low confidence, as if all of them were kind 2.
    soft = sorted(i for i, c in cls.items() if c == "kind1" and split[i].get("confidence") in {"medium", "low"})
    soft_ent = sum(cp[i]["abs_wbp"] for i in soft)
    lo_k1 = wilson(k1_up, len(refuted_k1))[0]
    return {
        "coupled_tasks": len(cp), "coupled_abs_wbp": coupled_total, "all_abs_wbp": total,
        "first_reader": {"tasks": dict(Counter(str(r["kind"]) for r in split.values())),
                         "by_rule": sum(r["reader"] == "rule" for r in split.values()),
                         "census_pairs": dict(Counter(f"{c['first']}/{c['refuter']}" for c in cp.values())),
                         "model_read_kind1": sum(r["kind"] == 1 and r["reader"] == "model" for r in split.values()),
                         "model_read_proposal_and_agents_followed": dict(Counter(
                             f"proposal={r.get('proposal_in_issue')},followed={r.get('agents_follow_proposal')}"
                             for r in split.values() if r["reader"] == "model")),
                         "kind1_proposal_followed": sum(r["kind"] == 1 and r.get("proposal_in_issue") is True
                                                        and r.get("agents_follow_proposal") is True
                                                        for r in split.values())},
        "refuter": {"rows": len(refute), "missing": missing,
                    "kind2_calls": len(refuted_k2), "kind2_upheld": sum(refute[i]["your_kind"] == 2 for i in refuted_k2),
                    "kind1_sample": sample, "kind1_sampled": len(refuted_k1),
                    "kind1_upheld": k1_up,
                    "kind1_upheld_wilson95": [round(x, 4) for x in wilson(k1_up, len(refuted_k1))],
                    "kind1_error_upper95": round(1 - lo_k1, 4),
                    "kind1_read_once": sum(c == "kind1" for c in cls.values()) - len(refuted_k1),
                    "kind1_read_once_by_model": sum(cls[i] == "kind1" and split[i]["reader"] == "model"
                                                    for i in split) - len(refuted_k1)},
        "sensitivity_soft_kind1": {"tasks": soft, "n": len(soft), "abs_wbp": soft_ent,
                                   "kind1_share_of_all_wbp_if_moved": round((ent.get("kind1", 0) - soft_ent) / total, 4),
                                   "kind2_share_of_all_wbp_if_moved": round((ent.get("kind2", 0) + soft_ent) / total, 4)},
        "tasks": {k: n.get(k, 0) for k in CLASSES},
        "abs_wbp": {k: ent.get(k, 0) for k in CLASSES},
        "share_of_all_wbp": {k: round(ent.get(k, 0) / total, 4) for k in CLASSES},
        "share_of_coupled_wbp": {k: round(ent.get(k, 0) / coupled_total, 4) for k in CLASSES},
        "task_ids": {k: sorted(i for i, c in cls.items() if c == k) for k in CLASSES},
        "sanity": {i: {"expected": e, "got": cls.get(i), "reader": split.get(i, {}).get("reader")}
                   for i, e in SANITY.items()},
        "complete": not missing,
    }


def merge(parts: Path, d: Path) -> int:
    """Write split_kind.jsonl: rule rows for interface/interface tasks plus reader rows from parts/first*.jsonl."""
    cp = coupled(d)
    rows = []
    for p in sorted(parts.glob("first*.jsonl")):
        for r in at.read_jsonl(p):
            if isinstance(r.get("kind"), str) and r["kind"] in {"1", "2"}:
                r["kind"] = int(r["kind"])
            rows.append({"instance_id": r["instance_id"], "reader": "model", **{k: v for k, v in r.items()
                                                                                 if k != "instance_id"}})
    hand = {r["instance_id"]: r for name in at.CENSUS_SETS if (d / name).is_file() for r in at.read_jsonl(d / name)}
    for iid in sorted(cp):
        if by_rule(cp[iid]):
            h = hand[iid]
            rows.append({"instance_id": iid, "reader": "rule", "kind": 1, "confidence": "high",
                         "top_test": h.get("top_test", ""), "evidence": h.get("issue_quote", ""),
                         "proposal_in_issue": None, "agents_follow_proposal": None,
                         "why": "Both census readers called the most-failed test `interface` (a gold-only name or "
                                "signature); the brief makes every interface case kind 1. Census: "
                                + h.get("test_requires", "")})
    rows.sort(key=lambda r: r["instance_id"])
    rows_by_id(rows, "kind", "merged")
    (d / "split_kind.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    print(f"{len(rows)} rows ({sum(r['reader'] == 'rule' for r in rows)} by rule); coupled tasks {len(cp)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path(__file__).resolve().parents[1] / "data/census")
    ap.add_argument("--merge", type=Path, help="reader parts directory (first*.jsonl)")
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)
    if a.merge:
        return merge(a.merge, a.dir)
    if a.sample:
        split = rows_by_id(at.read_jsonl(a.dir / "split_kind.jsonl"), "kind", "split_kind.jsonl")
        print("\n".join(refute_sample(split)))
        return 0
    out = tally(a.dir)
    text = json.dumps(out, indent=1)
    print(text)
    if not a.no_write and out["complete"]:
        (a.dir / "split_tally.json").write_text(text + "\n", encoding="utf-8")
    if not out["complete"]:
        print(f"refuter rows missing for {out['refuter']['missing']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
