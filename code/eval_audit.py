"""Frozen evaluator of the Gemma 4 auditor (card exp/cards/A1-gemma-auditor.md, "Primary"). Stdlib only.

    python eval_audit.py PREDS LABELS [--config configs/<config>.json] [--spot SPOT_LABELS] [--draws 2000] [--seed 0]

PREDS: rows {instance_id, model, verdict, parse_source} (run_auditor.py). LABELS: rows {instance_id, gold, set} with
gold in coupled / genuine / contested (build_packets.py). Scored per model on the decided tasks (gold coupled or
genuine). A prediction is coupled when its verdict is interface or gold_choice; any other verdict, None included, is
not coupled. A decided task with no row for a model counts in n_missing and is scored as not coupled.
Metrics per model: accuracy and Cohen's kappa (binary, coupled vs not), each with a 95% bootstrap CI over tasks
(resampled with replacement; a draw where kappa is undefined is skipped and counted); precision and recall of
coupled; the shares of parse sources; accuracy on the near-total set and on the random sample; the share of
contested tasks called coupled. scale_out_go = kappa >= 0.6, its CI low >= 0.4, the share without a verdict <= 0.05
and n_missing == 0 (fixed in the card before any run). contradiction = the best model's kappa < 0.2 or its CI
low <= 0.
--spot: a human annotator's spot-check letters, rows {instance_id, annotator} with annotator in C / G / U; agreement on C and G only
(C = coupled).
--config: every model the run's config names is scored; a model with no rows (it failed to load) is scored as all
missing, so best_kappa, contradiction and scale_out_go never silently drop it.
Exit 1 when no model has a row for a decided task (nothing to score), or the labels hold no decided task.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict

COUPLED = {"interface", "gold_choice"}
KAPPA_GO, KAPPA_LO_GO, NONE_SHARE_GO = 0.6, 0.4, 0.05
CONTRA_KAPPA = 0.2


def read_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def kappa(pairs: list[tuple[int, int]]):
    """Cohen's kappa for binary (gold, pred) pairs; None when chance agreement is 1."""
    n = len(pairs)
    if n == 0:
        return None
    po = sum(g == p for g, p in pairs) / n
    g1, p1 = sum(g for g, _ in pairs) / n, sum(p for _, p in pairs) / n
    pe = g1 * p1 + (1 - g1) * (1 - p1)
    return None if pe >= 1 else (po - pe) / (1 - pe)


def accuracy(pairs):
    return sum(g == p for g, p in pairs) / len(pairs) if pairs else None


def ci(values: list[float]):
    if not values:
        return None, None
    v = sorted(values)
    return v[int(0.025 * len(v))], v[min(len(v) - 1, int(0.975 * len(v)))]


def r4(x):
    return None if x is None else round(x, 4)


def metric(name, value):
    print(f"METRIC {name}={'nan' if value is None else value}")


def score_model(name: str, rows: dict[str, dict], labels: list[dict], draws: int, seed: int, spot: dict) -> dict:
    decided = [x for x in labels if x["gold"] in ("coupled", "genuine")]
    pred = {i: (r.get("verdict") in COUPLED) for i, r in rows.items()}
    pairs = {x["instance_id"]: (int(x["gold"] == "coupled"), int(pred.get(x["instance_id"], False))) for x in decided}
    ids = sorted(pairs)
    allp = [pairs[i] for i in ids]
    k, acc = kappa(allp), accuracy(allp)
    rng = random.Random(seed)
    ks, accs, skipped = [], [], 0
    for _ in range(draws):
        s = [pairs[rng.choice(ids)] for _ in ids]
        kk = kappa(s)
        if kk is None:
            skipped += 1
        else:
            ks.append(kk)
        accs.append(accuracy(s))
    k_lo, k_hi = ci(ks)
    a_lo, a_hi = ci(accs)
    tp = sum(g and p for g, p in allp)
    src = Counter(rows[i].get("parse_source") if i in rows else "missing" for i in ids)
    n_missing = sum(i not in rows for i in ids)
    no_verdict = sum(i not in rows or rows[i].get("verdict") is None for i in ids) / len(ids)
    sets = defaultdict(list)
    for x in decided:
        sets["near_total" if x["set"] == "near_total" else "random"].append(pairs[x["instance_id"]])
    contested = [x["instance_id"] for x in labels if x["gold"] == "contested"]
    go = (k is not None and k_lo is not None and k >= KAPPA_GO and k_lo >= KAPPA_LO_GO
          and no_verdict <= NONE_SHARE_GO and n_missing == 0)
    m = {"n_decided": len(ids), "n_missing": n_missing, "accuracy": r4(acc), "acc_ci95_lo": r4(a_lo),
         "acc_ci95_hi": r4(a_hi), "kappa": r4(k), "kappa_ci95_lo": r4(k_lo), "kappa_ci95_hi": r4(k_hi),
         "kappa_draws_skipped": skipped,
         "precision_coupled": r4(tp / sum(p for _, p in allp)) if any(p for _, p in allp) else None,
         "recall_coupled": r4(tp / sum(g for g, _ in allp)) if any(g for g, _ in allp) else None,
         "pred_coupled_share": r4(sum(p for _, p in allp) / len(allp)),
         "no_verdict_share": r4(no_verdict),
         "acc_near_total": r4(accuracy(sets["near_total"])), "acc_random": r4(accuracy(sets["random"])),
         "contested_called_coupled": r4(sum(pred.get(i, False) for i in contested) / len(contested))
         if contested else None,
         "scale_out_go": int(go)}
    for s in ("generated", "forced", "too_long", "nonfinite", "error", "missing"):
        m[f"share_{s}"] = r4(src[s] / len(ids))
    if spot:
        sp = [(int(v == "C"), int(pred.get(i, False))) for i, v in spot.items() if v in ("C", "G")]
        m["spot_n"] = len(sp)
        m["spot_agree"] = r4(accuracy(sp))
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("preds")
    ap.add_argument("labels")
    ap.add_argument("--spot")
    ap.add_argument("--config", help="the run's config: every model it names is scored, absent ones as all missing")
    ap.add_argument("--draws", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    labels = read_jsonl(a.labels)
    by_model: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in read_jsonl(a.preds):
        by_model[r["model"]][r["instance_id"]] = r
    if a.config:
        with open(a.config, encoding="utf-8") as fh:
            for m in json.load(fh)["models"]:
                by_model.setdefault(m["name"], {})
    spot = {r["instance_id"]: r["annotator"].strip().upper() for r in read_jsonl(a.spot)} if a.spot else {}
    decided = {x["instance_id"] for x in labels if x["gold"] in ("coupled", "genuine")}
    if not decided:
        print("no decided task in the labels", file=sys.stderr)
        return 1
    base = sum(x["gold"] == "coupled" for x in labels if x["instance_id"] in decided) / len(decided)
    metric("n_decided", len(decided))
    metric("base_rate_coupled", r4(base))
    scored = {}
    for name in sorted(by_model):
        m = score_model(name, by_model[name], labels, a.draws, a.seed, spot)
        scored[name] = m
        for k, v in m.items():
            metric(f"{name}.{k}", v)
    usable = {n: m for n, m in scored.items() if m["kappa"] is not None}
    best = max(usable, key=lambda n: usable[n]["kappa"]) if usable else None
    for name in sorted(scored):
        metric(f"{name}.is_best", int(name == best))
    metric("best_kappa", usable[best]["kappa"] if best else None)
    # The card's contradiction: the best model's kappa under 0.2, or its CI includes 0.
    lo = usable[best]["kappa_ci95_lo"] if best else None
    metric("contradiction", int(usable[best]["kappa"] < CONTRA_KAPPA or lo is None or lo <= 0) if best else None)
    metric("scale_out_go", int(any(m["scale_out_go"] for m in scored.values())))
    if not any(m["n_missing"] < m["n_decided"] for m in scored.values()):
        print("no model has a row for any decided task", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
