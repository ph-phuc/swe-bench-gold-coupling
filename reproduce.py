"""Recompute every headline number of the writeup from data/ and check it against draft_numbers.json.

    python reproduce.py            (from the release root; CPU only, no model calls, a few seconds)

Steps, each from the shipped files only:
  1. label table   data/labels/entries.csv (+ validity columns of data/census/per_task.csv)
  2. census        code/audit_tally.py on data/census/ (also: the shipped census JSON and task_verdicts.csv rebuild equal)
  2b. kind split  code/split_tally.py on data/census/ (equal to the shipped split_tally.json)
  3. system rates  code/system_rates.py, default and --kind2-genuine, into a temporary directory (both equal to
                  the shipped data/system_rates/); Figure 1's medians from its input CSV
  4. spot check    data/spotcheck/spotcheck_letters.json with code/spotcheck_agreement.py
  5. Gemma auditor code/eval_audit.py on data/auditor_benchmark/ (labels + the models' saved predictions)
  6. carried       two numbers read from shipped result files, not recomputed (see draft_numbers.json "carried")
Prints one line per check and exits 1 if any check fails. An entry with "correct" in draft_numbers.json is a number the
current draft prints wrongly: it is checked against the data and listed as DRAFT-FIX until the draft is fixed.
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "code"))

import audit_tally  # noqa: E402
import audit_prompt  # noqa: E402
import eval_audit  # noqa: E402
import split_tally  # noqa: E402
import system_rates  # noqa: E402
import task_verdicts  # noqa: E402
from wilson import wilson  # noqa: E402

DATA = ROOT / "data"
CENSUS = DATA / "census"


def read_csv(p: Path) -> list[dict]:
    with open(p, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# ---------------------------------------------------------------------------------------------------------------
def label_table() -> dict:
    rows = read_csv(DATA / "labels/entries.csv")
    judged = [r for r in rows if r["label_official"] == "1" and r["label_hardened"] in ("0", "1")]
    wbp = [r for r in judged if r["label_hardened"] == "0"]
    ut = [r for r in rows if r["label_official"] == "1" and r["label_utboost"] == "0"]
    per_task_j, per_task_w = Counter(r["instance_id"] for r in judged), Counter(r["instance_id"] for r in wbp)
    near = [t for t in per_task_j if per_task_j[t] >= 5 and per_task_w[t] / per_task_j[t] >= 0.9]
    pt = {t["instance_id"]: t for t in read_csv(CENSUS / "per_task.csv")}
    # The per-task counts the census code uses must equal the counts recomputed from the entries.
    bad = [t for t in pt if (int(pt[t]["abs_wbp"]), int(pt[t]["abs_judged"])) != (per_task_w[t], per_task_j[t])]
    if bad or set(pt) != {r["instance_id"] for r in rows}:
        raise SystemExit(f"per_task.csv disagrees with entries.csv on {bad[:5]}")
    valid = [all(t[k] == "True" for k in ("original_valid", "abs_valid", "utboost_valid")) for t in pt.values()]
    return {
        "entries": len(rows), "systems": len({r["system"] for r in rows}), "tasks": len(pt),
        "unique_patches": len({(r["instance_id"], r["sha"]) for r in rows}),
        "tasks_all_suites_valid": sum(valid), "tasks_with_any_invalid": len(valid) - sum(valid),
        "abs_judged": len(judged), "abs_wbp": len(wbp), "abs_wbp_rate_pct": 100 * len(wbp) / len(judged),
        "unique_abs_wbp": len({(r["instance_id"], r["sha"]) for r in wbp}),
        "tasks_with_abs_wbp": len(per_task_w), "utboost_wbp": len(ut),
        "tasks_with_utboost_wbp": len({r["instance_id"] for r in ut}),
        "near_total_tasks": len(near), "near_total_wbp": sum(per_task_w[t] for t in near),
    }


# ---------------------------------------------------------------------------------------------------------------
def census() -> dict:
    out = audit_tally.tally(CENSUS)
    shipped = json.loads((CENSUS / "audit_tally_census_2026-10-29.json").read_text(encoding="utf-8"))
    for k in ("census", "refuter") + audit_tally.CENSUS_SETS:
        if out[k] != shipped[k]:
            raise SystemExit(f"audit_tally output differs from the shipped census JSON in {k!r}")
    if task_verdicts.build(CENSUS) != (DATA / "task_verdicts.csv").read_text(encoding="utf-8"):
        raise SystemExit("data/task_verdicts.csv differs from a rebuild (python code/task_verdicts.py)")
    c, nt = out["census"], out["handread_near_total.jsonl"]
    ref = audit_tally.refuter_verdicts(CENSUS)
    first = {r["instance_id"]: r["category"] for n in audit_tally.CENSUS_SETS for r in read_jsonl(CENSUS / n)}
    refuted_first = Counter(first[i] for i in ref)
    other_c = c["abs_wbp"]["coupled"] - nt["abs_wbp"]["coupled"]
    other_all = c["abs_wbp_total"] - nt["abs_wbp_total"]
    got = {"read": c["read"], "refuter_verdicts": out["refuter"]["verdicts"], "refuter_upheld": out["refuter"]["upheld"],
           "near_total_coupled_tasks": nt["tasks"]["coupled"], "near_total_coupled_wbp": nt["abs_wbp"]["coupled"],
           "near_total_coupled_pct": 100 * nt["abs_wbp"]["coupled"] / nt["abs_wbp_total"],
           "other_tasks": c["tasks_with_wbp"] - sum(nt["tasks"].values()),
           "other_coupled_wbp": other_c, "other_wbp": other_all, "other_coupled_pct": 100 * other_c / other_all,
           "first_interface_of_refuted": refuted_first["interface"],
           "first_gold_choice_of_refuted": refuted_first["gold_choice"]}
    for k in ("coupled", "in_scope", "contested", "env"):
        got[f"tasks_{k}"] = c["tasks"][k]
        got[f"wbp_{k}"] = c["abs_wbp"][k]
        got[f"unique_{k}"] = c["unique_abs_wbp"][k]
        got[f"share_{k}_pct"] = 100 * c["abs_wbp"][k] / c["abs_wbp_total"]
    return got


# ---------------------------------------------------------------------------------------------------------------
def split() -> dict:
    s = split_tally.tally(CENSUS)
    shipped = json.loads((CENSUS / "split_tally.json").read_text(encoding="utf-8"))
    if s != shipped:
        raise SystemExit("split_tally output differs from the shipped data/census/split_tally.json")
    if not s["complete"] or any(s["tasks"][k] for k in ("kind1_contested", "kind2_contested", "unclear")):
        raise SystemExit("split not complete or has contested kinds")
    rf, so = s["refuter"], s["sensitivity_soft_kind1"]
    lo, hi = wilson(rf["kind1_upheld"], rf["kind1_sampled"])
    return {"coupled_tasks": s["coupled_tasks"], "kind1_tasks": s["tasks"]["kind1"], "kind2_tasks": s["tasks"]["kind2"],
            "kind1_wbp": s["abs_wbp"]["kind1"], "kind2_wbp": s["abs_wbp"]["kind2"],
            "kind1_share_pct": 100 * s["abs_wbp"]["kind1"] / s["all_abs_wbp"],
            "kind2_share_pct": 100 * s["abs_wbp"]["kind2"] / s["all_abs_wbp"],
            "kind1_of_coupled_pct": 100 * s["abs_wbp"]["kind1"] / s["coupled_abs_wbp"],
            "by_rule": s["first_reader"]["by_rule"], "model_read_kind1": s["first_reader"]["model_read_kind1"],
            "kind1_sampled": rf["kind1_sampled"], "kind1_upheld": rf["kind1_upheld"],
            "kind1_wilson_lo": lo, "kind1_wilson_hi": hi,
            "kind2_calls": rf["kind2_calls"], "kind2_upheld": rf["kind2_upheld"], "refuter_rows": rf["rows"],
            "soft_kind1": so["n"],
            "soft_kind1_share_pct": 100 * (s["abs_wbp"]["kind1"] - so["abs_wbp"]) / s["all_abs_wbp"],
            "soft_kind2_share_pct": 100 * (s["abs_wbp"]["kind2"] + so["abs_wbp"]) / s["all_abs_wbp"]}


# ---------------------------------------------------------------------------------------------------------------
def rates() -> tuple[dict, dict, dict]:
    shipped = DATA / "system_rates"
    with tempfile.TemporaryDirectory() as tmp:
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            for extra in ([], ["--kind2-genuine"]):
                rc = system_rates.main(["--dir", str(CENSUS), "--long", str(DATA / "labels/entries.csv"),
                                        "--out", tmp, "--draws", "2000", "--seed", "0", "--min-judged", "100"] + extra)
                if rc != 0:
                    raise SystemExit("system_rates.py failed")
        for name in ("per_system_corrected.csv", "per_system_corrected_summary.json",
                     "per_system_corrected_kind2genuine.csv", "per_system_corrected_kind2genuine_summary.json"):
            if (Path(tmp) / name).read_bytes().replace(b"\r\n", b"\n") != \
                    (shipped / name).read_bytes().replace(b"\r\n", b"\n"):
                raise SystemExit(f"system_rates.py output {name} differs from data/system_rates/{name} "
                                 "(a different numpy version can move bootstrap bounds; see README)")
        s = json.loads((Path(tmp) / "per_system_corrected_summary.json").read_text(encoding="utf-8"))
        k2 = json.loads((Path(tmp) / "per_system_corrected_kind2genuine_summary.json").read_text(encoding="utf-8"))
        k2_cor = np.array([float(r["in_scope_rate"]) for r in read_csv(Path(tmp) / "per_system_corrected_kind2genuine.csv")
                           if r["ranked"] == "True"])
        rows = [r for r in read_csv(Path(tmp) / "per_system_corrected.csv") if r["ranked"] == "True"]
    raw = np.array([float(r["raw_rate"]) for r in rows])
    cor = np.array([float(r["in_scope_rate"]) for r in rows])
    ratio = cor / raw
    share = np.array([float(r["coupled_share_of_wbp"]) for r in rows])
    width = np.array([float(r["rank_change_hi"]) - float(r["rank_change_lo"]) for r in rows])
    tb, rk = s["tasks_by_class"], s["ranked"]
    return {
        "draws": s["draws"], "tasks_raw": s["tasks"], "tasks_in_scope": tb["in_scope"] + tb["no_wbp"],
        "tasks_excl_coupled": s["tasks"] - tb["coupled"], "tasks_no_wbp": tb["no_wbp"],
        "judged_in_scope": s["judged_by_group"]["in_scope"], "judged_excl_coupled": s["judged_by_group"]["excl_coupled"],
        "wbp_in_scope": s["wbp_by_group"]["in_scope"], "wbp_excl_coupled": s["wbp_by_group"]["excl_coupled"],
        "pooled_raw_pct": 100 * s["wbp_by_group"]["raw"] / s["judged_by_group"]["raw"],
        "pooled_in_scope_pct": 100 * s["wbp_by_group"]["in_scope"] / s["judged_by_group"]["in_scope"],
        "pooled_excl_coupled_pct": 100 * s["wbp_by_group"]["excl_coupled"] / s["judged_by_group"]["excl_coupled"],
        "ranked_systems": s["ranked_systems"],
        "median_raw_pct": 100 * float(np.median(raw)), "median_in_scope_pct": 100 * float(np.median(cor)),
        "iqr_raw_lo_pct": 100 * float(np.percentile(raw, 25)), "iqr_raw_hi_pct": 100 * float(np.percentile(raw, 75)),
        "iqr_in_scope_lo_pct": 100 * float(np.percentile(cor, 25)),
        "iqr_in_scope_hi_pct": 100 * float(np.percentile(cor, 75)),
        "ratio_min": float(ratio.min()), "ratio_max": float(ratio.max()),
        "ratio_iqr_lo": float(np.percentile(ratio, 25)), "ratio_iqr_hi": float(np.percentile(ratio, 75)),
        "median_coupled_share_pct": 100 * float(np.median(share)),
        "spearman": rk["spearman_raw_vs_in_scope"], "median_rank_interval_width": float(np.median(width)),
    }, {
        "kind2_tasks": len(k2["kind2_genuine"]["tasks"]),
        "pooled_in_scope_pct": 100 * k2["wbp_by_group"]["in_scope"] / k2["judged_by_group"]["in_scope"],
        "pooled_excl_coupled_pct": 100 * k2["wbp_by_group"]["excl_coupled"] / k2["judged_by_group"]["excl_coupled"],
        "median_in_scope_pct": 100 * float(np.median(k2_cor)),
    }, {
        # Figure 1 draws these from per_system_corrected.csv (figures/fig1_rates.py; matplotlib not needed here).
        "systems": len(rows), "median_raw_pct": 100 * float(np.median(raw)),
        "median_corrected_pct": 100 * float(np.median(cor)),
    }


# ---------------------------------------------------------------------------------------------------------------
def spot() -> dict:
    """The blind spot check: five annotators (a1 an author, a2-a5 external) on 10 tasks."""
    import contextlib
    import io
    import spotcheck_agreement as SA
    d = json.loads((DATA / "spotcheck/spotcheck_letters.json").read_text(encoding="utf-8"))
    first = {r["instance_id"]: r["category"] for n in audit_tally.CENSUS_SETS for r in read_jsonl(CENSUS / n)}
    ref = audit_tally.refuter_verdicts(CENSUS)
    model = ["C" if audit_tally.classify(first[i], ref.get(i)) == "coupled" else "G" for i in d["tasks"]]
    if model != d["model"]:
        raise SystemExit("spotcheck_letters.json model letters differ from the census verdicts")
    with tempfile.TemporaryDirectory() as tmp:
        saved, SA.OUT = SA.OUT, Path(tmp) / "agreement.json"
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                SA.main()
            out = json.loads(SA.OUT.read_text(encoding="utf-8"))
        finally:
            SA.OUT = saved
    if out != json.loads((DATA / "spotcheck/spotcheck_agreement.json").read_text(encoding="utf-8")):
        raise SystemExit("spotcheck_agreement.py output differs from data/spotcheck/spotcheck_agreement.json")
    st = json.loads((CENSUS / "split_tally.json").read_text(encoding="utf-8"))
    split, soft = st["task_ids"], set(st["sensitivity_soft_kind1"]["tasks"])
    ann = d["annotators"]
    votes = {task: [ann[x][k] for x in ann] for k, task in enumerate(d["tasks"])}
    maj = {task: t["majority"] for task, t in ((t["task"], t) for t in out["per_task"])}
    ctrl = [task for task, m in zip(d["tasks"], model) if m == "G"]
    k1 = [task for task in d["tasks"] if task in split["kind1"]]
    k2 = [task for task in d["tasks"] if task in split["kind2"]]
    pa = out["per_annotator"]
    return {"tasks": len(model), "annotators": len(ann), "controls": len(ctrl),
            "controls_g_all_five": sum(all(v == "G" for v in votes[c]) for c in ctrl),
            "model_mean_cohen": sum(v["kappa_vs_model"] for v in pa.values()) / len(pa),
            "fleiss_humans": out["fleiss_kappa_humans"],
            "mean_pairwise_cohen_humans": out["mean_pairwise_cohen_humans"],
            "majority_agrees_model": out["majority_agrees_model"],
            "kind2_majority_g": sum(maj[x] == "G" for x in k2),
            "g_votes_13410": votes["django__django-13410"].count("G"),
            "g_votes_16527": votes["django__django-16527"].count("G"),
            "kind1_tasks_checked": len(k1), "kind1_majority_c": sum(maj[x] == "C" for x in k1),
            "g_votes_11292": votes["django__django-11292"].count("G"),
            "strict_annotator_g": max(sum(v == "G" for v in labs) for labs in ann.values()),
            "strict_annotators": sum(sum(v == "G" for v in labs) >= 8 for labs in ann.values()),
            "kind2_tasks_checked": len(k2),
            "a1_disagreements_are_kind2": sum(ann["a1"][k] != model[k] and task in split["kind2"]
                                              for k, task in enumerate(d["tasks"]))
            if sum(ann["a1"][k] != model[k] for k in range(len(model))) == 2 else -1,
            "votes_13410_others_c": votes["django__django-13410"].count("C"),
            "votes_16527_others_c": votes["django__django-16527"].count("C"),
            "votes_11292_others_c": votes["django__django-11292"].count("C"),
            "medium_conf_11292": int("django__django-11292" in soft and "django__django-11292" in split["kind1"])}


# ---------------------------------------------------------------------------------------------------------------
def auditor() -> dict:
    b = DATA / "auditor_benchmark"
    labels = read_jsonl(b / "labels.jsonl")
    decided = [x for x in labels if x["gold"] in ("coupled", "genuine")]
    got = {"packets": len(read_jsonl(b / "packet_index.jsonl")), "n_decided": len(decided),
           "base_rate_pct": 100 * sum(x["gold"] == "coupled" for x in decided) / len(decided),
           "coupled_in_reference": sum(x["gold"] == "coupled" for x in decided)}
    if {x["instance_id"] for x in labels} != {p["instance_id"] for p in read_jsonl(b / "packet_index.jsonl")}:
        raise SystemExit("labels.jsonl and packet_index.jsonl hold different tasks")
    gold = {x["instance_id"]: x["gold"] for x in decided}
    for fname, models in (("a1-r1-e4b-12b.jsonl", ("e4b", "g12b")), ("a1-31b-nf4.jsonl", ("g31b_nf4",))):
        preds = defaultdict(dict)
        for r in read_jsonl(b / "predictions" / fname):
            # Score from the raw model text, not the saved verdict field.
            if r.get("parse_source") == "generated" and audit_prompt.parse(r.get("raw") or "") != r["verdict"]:
                raise SystemExit(f"{fname}: saved verdict differs from a re-parse of raw for {r['instance_id']}")
            preds[r["model"]][r["instance_id"]] = r
        for m in models:
            s = eval_audit.score_model(m, preds[m], labels, 2000, 0, {})
            key = "g31b" if m == "g31b_nf4" else m
            flags = [i for i in gold if preds[m].get(i, {}).get("verdict") in eval_audit.COUPLED]
            got.update({f"{key}_kappa": s["kappa"], f"{key}_kappa_lo": s["kappa_ci95_lo"],
                        f"{key}_kappa_hi": s["kappa_ci95_hi"], f"{key}_calls_coupled_pct": 100 * s["pred_coupled_share"],
                        f"{key}_precision": s["precision_coupled"], f"{key}_recall": s["recall_coupled"],
                        f"{key}_flags": len(flags), f"{key}_flags_agree": sum(gold[i] == "coupled" for i in flags)})
            if m == "g12b":
                got["g12b_coupled_missed"] = sum(gold[i] == "coupled" for i in gold) - got["g12b_flags_agree"]
                got["g12b_coupled_called_in_scope"] = sum(
                    gold[i] == "coupled" and preds[m].get(i, {}).get("verdict") == "in_scope" for i in gold)
    return got


def carried(spec: dict) -> dict:
    out = {}
    for k, v in spec.items():
        if k.startswith("_"):
            continue
        out[k] = json.loads((ROOT / v["file"]).read_text(encoding="utf-8"))[v["key"]]
    return out


# ---------------------------------------------------------------------------------------------------------------
def check(section: str, got: dict, spec: dict) -> list[str]:
    fails = []
    for k, v in spec.items():
        if k.startswith("_"):
            continue
        if k not in got:
            fails.append(f"{section}.{k}: not computed")
            continue
        g, d, dec = got[k], v.get("correct", v["draft"]), v.get("dec")
        if dec is None:
            ok = isinstance(g, (int, np.integer)) and int(g) == d
        else:
            ok = g is not None and abs(float(g) - d) <= 0.5 * 10 ** -dec + 1e-9
        shown = f"{g}" if dec is None else f"{float(g):.{dec + 2}f}"
        print(f"{'OK  ' if ok else 'FAIL'} {section}.{k}: computed {shown}, draft {v['draft']}   [{v['where']}]")
        if "draft_fix" in v:
            print(f"     DRAFT-FIX {section}.{k}: the draft prints {v['draft']}, the data give {d}: {v['draft_fix']}")
        if not ok:
            fails.append(f"{section}.{k}")
    return fails


def main() -> int:
    t0 = time.time()
    spec = json.loads((ROOT / "draft_numbers.json").read_text(encoding="utf-8"))
    sr, k2, fig = rates()
    results = {"label_table": label_table(), "census": census(), "split": split(), "system_rates": sr,
               "kind2_genuine": k2, "figure1": fig, "spot_check": spot(), "auditor": auditor(),
               "carried": carried(spec["carried"])}
    fails, n = [], 0
    for section, got in results.items():
        n += sum(1 for k in spec[section] if not k.startswith("_"))
        fails += check(section, got, spec[section])
    print(f"elapsed {time.time() - t0:.1f} s")
    if fails:
        print(f"{len(fails)} OF {n} CHECKS FAIL: {fails}")
        return 1
    fixes = sum("draft_fix" in v for s in spec.values() if isinstance(s, dict) for v in s.values() if isinstance(v, dict))
    print(f"ALL {n} CHECKS PASS" + (f" ({fixes} draft numbers to fix, listed as DRAFT-FIX above)" if fixes else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
