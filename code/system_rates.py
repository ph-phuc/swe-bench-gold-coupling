"""Corrected per-system ABS wrong-but-passing rates: the 151 systems with the census's gold-coupled tasks set apart.

    python code/system_rates.py [--dir data/census] [--long data/labels/entries.csv] [--out DIR]
        [--draws 2000] [--seed 0] [--min-judged 100] [--kind2-genuine]

Task classes come from the 29/10 census (audit_tally.py: first reader plus refuter): coupled, contested, in_scope,
env; a task with no ABS wbp entry at all was not read and is `no_wbp`. The verdict is per task, not per patch: a
coupled task can still hold genuinely wrong patches (docs/w1-label-table-2026-10-27.md, "Limits of the audit").

An entry is one system's submission for one task (label_long.csv, written by label_table.py --long). It is judged
when it passes our original re-run and ABS gives a verdict: wbp (fails ABS) or pass. Per system, wbp / judged over:
  raw          every task (matches per_system.csv);
  in_scope     tasks read in_scope plus tasks with no wbp (the corrected rate);
  excl_coupled every task except coupled ones (contested and env kept: the lenient corrected rate);
  coupled      coupled tasks only;  contested  contested tasks only.
95% intervals: percentile bootstrap that resamples the 470 tasks with replacement (one draw serves every system, so
ranks move together); a draw where a system has no judged entry in that group is skipped for that system.
Ranks (1 = highest rate) are over systems with at least --min-judged judged entries in total.

Writes per_system_corrected.csv and per_system_corrected_summary.json into --out (default: --dir).
(Release copy: only the defaults and --out differ from the run's code.) Exits 1 when a count fails to
reconcile with per_system.csv, per_task.csv or the census totals.

--kind2-genuine: the 03/11 split (split_tally.json, docs/gold-choice-split-2026-11-03.md) divides the coupled tasks
into kind 1 (the test pins a gold artefact) and kind 2 (the test checks a gold improvement over the issue's own
proposed fix). With this flag the kind-2 tasks become their own class `kind2`, counted as genuine: in raw, in_scope
and excl_coupled, and out of coupled (which then holds kind 1 only); a `kind2` group is added. Reconciliation runs on
the census classes first, so it is unchanged. Outputs go to per_system_corrected_kind2genuine.csv and
per_system_corrected_kind2genuine_summary.json; the default outputs are not touched. In those outputs
`coupled_share_of_wbp` counts kind-1 tasks only (the summary says so under `kind2_genuine`).
"""

from __future__ import annotations

import argparse
import csv
import json
import warnings
from pathlib import Path

import numpy as np

from audit_tally import CENSUS_SETS, classify, read_jsonl, refuter_verdicts, unique_rows

GROUPS = {"raw": {"coupled", "contested", "in_scope", "env", "no_wbp"},
          "in_scope": {"in_scope", "no_wbp"},
          "excl_coupled": {"contested", "in_scope", "env", "no_wbp"},
          "coupled": {"coupled"},
          "contested": {"contested"}}
# --kind2-genuine: kind-2 tasks counted as genuine; same group order, plus a kind2 group at the end.
GROUPS_KIND2 = {"raw": GROUPS["raw"] | {"kind2"},
                "in_scope": GROUPS["in_scope"] | {"kind2"},
                "excl_coupled": GROUPS["excl_coupled"] | {"kind2"},
                "coupled": {"coupled"},
                "contested": {"contested"},
                "kind2": {"kind2"}}


def kind2_ids(d: Path) -> list[str]:
    """The kind-2 task ids from split_tally.json; exits unless the list agrees with its task count."""
    try:
        t = json.loads((d / "split_tally.json").read_text(encoding="utf-8"))
        listed, count = t["task_ids"]["kind2"], t["tasks"]["kind2"]
    except (OSError, KeyError, TypeError, ValueError) as e:
        raise SystemExit(f"split_tally.json not usable for --kind2-genuine: {e!r}")
    ids = sorted(set(listed))
    if not ids or len(ids) != count or len(ids) != len(listed):
        raise SystemExit(f"split_tally.json: kind2 ids {ids} vs tasks.kind2 {count}")
    return ids


def task_classes(d: Path, wbp_by_task: dict[str, int]) -> dict[str, str]:
    """instance_id -> census class for every task in per_task.csv; exits when a task with wbp is unread or a coupled
    first verdict has no refuter verdict, or a read task has no wbp."""
    ref = refuter_verdicts(d)
    cls: dict[str, str] = {}
    for name in CENSUS_SETS:
        for r in unique_rows(read_jsonl(d / name), "category", name):
            if r["instance_id"] in cls:
                raise SystemExit(f"{r['instance_id']} is read in two sets")
            cls[r["instance_id"]] = classify(r["category"], ref.get(r["instance_id"]))
    bad = sorted(i for i, k in cls.items() if k == "coupled_unrefuted" or wbp_by_task.get(i, 0) <= 0)
    unread = sorted(i for i, w in wbp_by_task.items() if w > 0 and i not in cls)
    if bad or unread:
        raise SystemExit(f"census not usable: unrefuted or no-wbp read tasks {bad}, unread tasks {unread}")
    # raw lists its classes by name, so a class it does not list (e.g. audit_tally's "unclear") would drop silently.
    stray = sorted(i for i, k in cls.items() if k not in GROUPS["raw"])
    if stray:
        raise SystemExit(f"tasks in a class no group covers: {[(i, cls[i]) for i in stray]}")
    return {i: cls.get(i, "no_wbp") for i in wbp_by_task}


def entry_bucket(row: dict) -> str | None:
    """'wbp', 'pass' or None (not judged), as label_table.bucket: judged only when the original re-run passes."""
    if row["label_official"] != "1" or row["label_hardened"] not in ("0", "1"):
        return None
    return "wbp" if row["label_hardened"] == "0" else "pass"


def matrices(long_rows: list[dict], systems: list[str], tasks: list[str]):
    """Systems x tasks count matrices of wbp and judged entries."""
    si, ti = {s: k for k, s in enumerate(systems)}, {t: k for k, t in enumerate(tasks)}
    wbp = np.zeros((len(systems), len(tasks)))
    judged = np.zeros_like(wbp)
    for r in long_rows:
        b = entry_bucket(r)
        if b is None:
            continue
        s, t = si[r["system"]], ti[r["instance_id"]]
        judged[s, t] += 1
        wbp[s, t] += b == "wbp"
    return wbp, judged


def ranks(values: np.ndarray) -> np.ndarray:
    """Average ranks, 1 = highest value (ties share the mean of their positions). Values must be finite."""
    if not np.all(np.isfinite(values)):
        raise ValueError("ranks() needs finite values")
    order = np.argsort(-values, kind="stable")
    r = np.empty(len(values))
    r[order] = np.arange(1, len(values) + 1)
    for v in np.unique(values):
        tied = values == v
        r[tied] = r[tied].mean()
    return r


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(ranks(a), ranks(b))[0, 1])


def build(d: Path, long_path: Path, draws: int, seed: int, kind2: list[str] | None = None):
    with open(d / "per_task.csv", encoding="utf-8") as fh:
        per_task = {t["instance_id"]: t for t in csv.DictReader(fh)}
    with open(d / "per_system.csv", encoding="utf-8") as fh:
        per_system = {s["system"]: s for s in csv.DictReader(fh)}
    with open(long_path, encoding="utf-8") as fh:
        long_rows = list(csv.DictReader(fh))
    tasks, systems = sorted(per_task), sorted(per_system)
    cls = task_classes(d, {i: int(t["abs_wbp"]) for i, t in per_task.items()})
    wbp, judged = matrices(long_rows, systems, tasks)

    # Reconcile with the files the census and the label table already report.
    problems = []
    for k, s in enumerate(systems):
        got = (int(wbp[k].sum()), int(judged[k].sum()))
        want = (int(per_system[s]["abs_wbp"]), int(per_system[s]["abs_judged"]))
        if got != want:
            problems.append(f"{s}: wbp/judged {got} vs per_system.csv {want}")
    for k, t in enumerate(tasks):
        got = (int(wbp[:, k].sum()), int(judged[:, k].sum()))
        want = (int(per_task[t]["abs_wbp"]), int(per_task[t]["abs_judged"]))
        if got != want:
            problems.append(f"{t}: wbp/judged {got} vs per_task.csv {want}")
    census = json.loads((d / "audit_tally_census_2026-10-29.json").read_text(encoding="utf-8"))["census"]
    class_of = np.array([cls[t] for t in tasks])
    by_class = {c: int(wbp[:, class_of == c].sum()) for c in sorted(set(class_of))}
    for c, n in census["abs_wbp"].items():
        if by_class.get(c, 0) != n:
            problems.append(f"class {c}: {by_class.get(c, 0)} wbp entries vs census {n}")
    if by_class.get("no_wbp", 0) or int(wbp.sum()) != census["abs_wbp_total"]:
        problems.append(f"wbp total {int(wbp.sum())} (no_wbp {by_class.get('no_wbp', 0)}) vs census "
                        f"{census['abs_wbp_total']}")
    if problems:
        raise SystemExit("reconciliation failed:\n  " + "\n  ".join(problems[:20]))

    groups = GROUPS
    if kind2 is not None:
        not_coupled = sorted(t for t in kind2 if cls.get(t) != "coupled")
        if not_coupled:
            raise SystemExit(f"kind-2 tasks not coupled in the census: {not_coupled}")
        k2 = set(kind2)
        class_of = np.array(["kind2" if t in k2 else c for t, c in zip(tasks, class_of)])
        groups = GROUPS_KIND2

    rng = np.random.default_rng(seed)
    counts = rng.multinomial(len(tasks), np.full(len(tasks), 1 / len(tasks)), size=draws).T  # tasks x draws
    out: dict[str, dict] = {}
    for g, members in groups.items():
        mask = np.isin(class_of, list(members)).astype(float)
        w, j = wbp * mask, judged * mask
        num, den = w.sum(1), j.sum(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            point = np.where(den > 0, num / den, np.nan)
            boot = (w @ counts) / (j @ counts)          # systems x draws; nan where a draw has no judged entry
        boot = np.where(np.isfinite(boot), boot, np.nan)
        with warnings.catch_warnings():               # a system with no judged entry in this group: all-nan row
            warnings.simplefilter("ignore", RuntimeWarning)
            lo, hi = np.nanpercentile(boot, [2.5, 97.5], axis=1)
        out[g] = {"wbp": num, "judged": den, "rate": point, "lo": np.where(den > 0, lo, np.nan),
                  "hi": np.where(den > 0, hi, np.nan), "boot": boot}
    return systems, tasks, class_of, out, per_system, groups


def fmt(x: float) -> str:
    return "" if not np.isfinite(x) else f"{x:.4f}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("data/census"))
    ap.add_argument("--long", type=Path, default=Path("data/labels/entries.csv"))
    ap.add_argument("--out", type=Path, default=None, help="output directory (default: --dir)")
    ap.add_argument("--draws", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--min-judged", type=int, default=100)
    ap.add_argument("--kind2-genuine", action="store_true",
                    help="count the split's kind-2 tasks as genuine; writes *_kind2genuine outputs")
    a = ap.parse_args(argv)
    if a.draws < 40:
        raise SystemExit("--draws must be at least 40 for a 95% percentile interval")
    kind2 = kind2_ids(a.dir) if a.kind2_genuine else None
    systems, tasks, class_of, g, per_system, groups = build(a.dir, a.long, a.draws, a.seed, kind2)
    stem = "per_system_corrected_kind2genuine" if kind2 is not None else "per_system_corrected"
    out_dir = a.out or a.dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Ranked: enough judged entries overall, and at least one on in_scope tasks (else no corrected rate to rank).
    ranked = (g["raw"]["judged"] >= a.min_judged) & (g["in_scope"]["judged"] > 0)
    idx = np.flatnonzero(ranked)
    r_raw = np.full(len(systems), np.nan)
    r_cor = np.full(len(systems), np.nan)
    r_raw[idx], r_cor[idx] = ranks(g["raw"]["rate"][idx]), ranks(g["in_scope"]["rate"][idx])
    # Paired interval for the rank change: both rankings redone on the same task draw (ordinal ranks; a draw where a
    # system has no judged entry ranks it last).
    move_lo, move_hi = np.full(len(systems), np.nan), np.full(len(systems), np.nan)

    def ordinal(m: np.ndarray) -> np.ndarray:
        return np.argsort(np.argsort(-np.nan_to_num(m, nan=-1.0), axis=0, kind="stable"), axis=0, kind="stable")

    moved = ordinal(g["raw"]["boot"][idx]) - ordinal(g["in_scope"]["boot"][idx])     # ranked systems x draws
    move_lo[idx], move_hi[idx] = np.percentile(moved, [2.5, 97.5], axis=1)

    rows = []
    for k, s in enumerate(systems):
        row = {"system": s, "tasks": per_system[s]["tasks"], "ranked": bool(ranked[k])}
        for name in groups:
            row.update({f"{name}_wbp": int(g[name]["wbp"][k]), f"{name}_judged": int(g[name]["judged"][k]),
                        f"{name}_rate": fmt(g[name]["rate"][k]), f"{name}_lo": fmt(g[name]["lo"][k]),
                        f"{name}_hi": fmt(g[name]["hi"][k])})
        row["coupled_share_of_wbp"] = fmt(g["coupled"]["wbp"][k] / g["raw"]["wbp"][k]) if g["raw"]["wbp"][k] else ""
        row["rank_raw"] = "" if np.isnan(r_raw[k]) else r_raw[k]
        row["rank_in_scope"] = "" if np.isnan(r_cor[k]) else r_cor[k]
        row["rank_change"] = "" if np.isnan(r_raw[k]) else r_raw[k] - r_cor[k]   # > 0: moves up (higher rate)
        row["rank_change_lo"] = "" if np.isnan(move_lo[k]) else move_lo[k]
        row["rank_change_hi"] = "" if np.isnan(move_hi[k]) else move_hi[k]
        rows.append(row)
    with open(out_dir / f"{stem}.csv", "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)

    raw, cor = g["raw"], g["in_scope"]
    ri = idx
    moves = [(abs(r_raw[k] - r_cor[k]), systems[k]) for k in ri]
    top = sorted(moves, key=lambda m: (-m[0], m[1]))[:5]
    # A system "drops" when its corrected rate sits below its raw interval's lower end.
    drop = int(np.sum(cor["rate"][ri] < raw["lo"][ri]))
    summary = {
        "draws": a.draws, "seed": a.seed, "min_judged": a.min_judged,
        "systems": len(systems), "ranked_systems": int(ranked.sum()), "tasks": len(tasks),
        "tasks_by_class": {c: int(np.sum(class_of == c)) for c in sorted(set(class_of))},
        "wbp_by_group": {n: int(g[n]["wbp"].sum()) for n in groups},
        "judged_by_group": {n: int(g[n]["judged"].sum()) for n in groups},
        "pooled_rate": {n: round(float(g[n]["wbp"].sum() / g[n]["judged"].sum()), 4) if g[n]["judged"].sum() else None
                        for n in groups},
        "ranked": {
            "median_rate_raw": round(float(np.median(raw["rate"][ri])), 4),
            "iqr_raw": [round(float(q), 4) for q in np.percentile(raw["rate"][ri], [25, 75])],
            "median_rate_in_scope": round(float(np.median(cor["rate"][ri])), 4),
            "iqr_in_scope": [round(float(q), 4) for q in np.percentile(cor["rate"][ri], [25, 75])],
            "spearman_raw_vs_in_scope": round(spearman(raw["rate"][ri], cor["rate"][ri]), 4),
            "corrected_below_raw_ci": drop,
            "rank_moves_ge_10": int(sum(m >= 10 for m, _ in moves)),
            "rank_moves_ge_20": int(sum(m >= 20 for m, _ in moves)),
            "rank_change_ci_excludes_0": int(np.sum((move_lo[ri] > 0) | (move_hi[ri] < 0))),
            "top5_rank_moves": [{"system": s, "rank_raw": float(r_raw[systems.index(s)]),
                                 "rank_in_scope": float(r_cor[systems.index(s)]),
                                 "rank_change_ci": [float(move_lo[systems.index(s)]),
                                                    float(move_hi[systems.index(s)])],
                                 "raw_rate": round(float(raw["rate"][systems.index(s)]), 4),
                                 "in_scope_rate": round(float(cor["rate"][systems.index(s)]), 4),
                                 "coupled_share_of_wbp": round(float(g["coupled"]["wbp"][systems.index(s)]
                                                                     / raw["wbp"][systems.index(s)]), 4)
                                 if raw["wbp"][systems.index(s)] else None}
                                for _, s in top],
        },
    }
    if kind2 is not None:
        summary["kind2_genuine"] = {"tasks": kind2, "source": "split_tally.json task_ids.kind2",
                                    "note": "coupled = kind 1 only here, so coupled_share_of_wbp is the kind-1 share"}
    (out_dir / f"{stem}_summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
