"""Score offline test auditors on the held-out board (writeup Table 4 and Section 7). Stdlib only, CPU, a few seconds.

    python code/score_heldout.py                                   (from the release root: the board)
    python code/score_heldout.py --preds my_auditor.jsonl --name "my auditor"     (adds your row)

Tasks: data/auditor_benchmark/heldout/labels.jsonl, 220 held-out census tasks; the 205 whose reference is coupled or
genuine are scored (64 coupled), contested and other are left out. The reference is the census verdict (two cloud
reads), not ground truth.

Rows printed (flagged, of them coupled, precision with a Wilson 95% interval, recall, AUROC of the score):
  1. no model: top 20% (41 of 205) by SWE-ABS rejection share abs_wbp / abs_judged (in labels.jsonl);
  2. Gemma 4 12B, prompted (A2): heldout/predictions/a2-g12b.jsonl, flagged where `coupled` is true;
  3. top 20%, then Gemma 12B as second read: the row-1 tasks that row 2 also flags;
  random: the base rate as precision, AUROC 0.5;
  then A2's Cohen's kappa with its bootstrap interval and recall, and the paired AUROC difference A2 - rule.

Your predictions (--preds): JSONL, one row per task, {"instance_id": ..., "coupled": true | false | null,
"score": float | null}; "p_coupled" is read when "score" is absent or null. Only `coupled: true` flags a task; false,
null or a missing row is not flagged (and counts as "not coupled" in kappa). Rows for tasks not on the board are
ignored with a warning, and a file that names no decided board task stops with an error. The score is optional and ranks tasks for
AUROC (higher = more likely coupled); a missing or non-finite score ranks last. Extra fields are ignored.

The statistics are the original analysis code, copied so the intervals match it exactly:
  - kappa, its interval and recall: eval_a2.py (task bootstrap, 2,000 draws, seed 0, a fresh RNG per statistic,
    interval = sorted values at int(0.025 n) and int(0.975 n));
  - AUROC and the paired AUROC difference: gemma_ranker.py (one RNG, 2,000 draws, seed 0, draws holding one class
    only are skipped, interval = sorted values at int(f (n - 1)); the difference is the mean over draws);
  - Wilson interval: code/wilson.py.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from wilson import wilson  # noqa: E402

BOARD = HERE.parent / "data" / "auditor_benchmark" / "heldout"
DRAWS, SEED, TOP_SHARE = 2000, 0, 0.2


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8-sig").splitlines() if x.strip()]


# --- from eval_a2.py (frozen evaluator of card A2), unchanged ------------------------------------------------------
def kappa(pairs):
    n = len(pairs)
    if n == 0:
        return None
    po = sum(g == p for g, p in pairs) / n
    g1, p1 = sum(g for g, _ in pairs) / n, sum(p for _, p in pairs) / n
    pe = g1 * p1 + (1 - g1) * (1 - p1)
    return None if pe >= 1 else (po - pe) / (1 - pe)


def ci(values):
    if not values:
        return None, None
    v = sorted(values)
    return v[int(0.025 * len(v))], v[min(len(v) - 1, int(0.975 * len(v)))]


def boot(ids, fn, draws, seed):
    """(values of fn over bootstrap resamples of ids, number of draws where fn was None)."""
    rng = random.Random(seed)
    vals, skipped = [], 0
    for _ in range(draws):
        v = fn([rng.choice(ids) for _ in ids])
        if v is None:
            skipped += 1
        else:
            vals.append(v)
    return vals, skipped


# --- from gemma_ranker.py (exploratory triage ranker), unchanged ---------------------------------------------------
def auroc(ids, score, gold) -> float:
    pos = [score[i] for i in ids if gold[i]]
    neg = [score[i] for i in ids if not gold[i]]
    s = sum((p > q) + 0.5 * (p == q) for p in pos for q in neg)
    return s / (len(pos) * len(neg))


def quantiles(xs):
    return [sorted(xs)[int(f * (len(xs) - 1))] for f in (0.025, 0.975)]


def paired_auroc_diff(ids, gold, a: dict, b: dict, draws=DRAWS, seed=SEED) -> dict:
    """AUROC(a) - AUROC(b) over task bootstrap draws (gemma_ranker.py's loop): mean of the draws and its interval."""
    rng = random.Random(seed)
    diffs = []
    for _ in range(draws):
        s = [rng.choice(ids) for _ in ids]
        if not any(gold[i] for i in s) or all(gold[i] for i in s):
            continue
        diffs.append(auroc(s, a, gold) - auroc(s, b, gold))
    lo, hi = quantiles(diffs)
    return {"diff": sum(diffs) / len(diffs), "lo": lo, "hi": hi, "point": auroc(ids, a, gold) - auroc(ids, b, gold),
            "draws_used": len(diffs)}


# --- the board -----------------------------------------------------------------------------------------------------
def load_board(board: Path = BOARD) -> tuple[dict, dict]:
    """(gold {id: 0/1} over decided tasks, rejection share {id: abs_wbp / abs_judged})."""
    labels = read_jsonl(board / "labels.jsonl")
    gold = {x["instance_id"]: int(x["gold"] == "coupled") for x in labels if x["gold"] in ("coupled", "genuine")}
    share = {x["instance_id"]: x["abs_wbp"] / x["abs_judged"] for x in labels if x["instance_id"] in gold}
    return gold, share


def load_preds(path: Path) -> tuple[set, dict]:
    """(ids flagged coupled, ranking score {id: float}, missing or non-finite = -1.0) from a predictions file."""
    rows = {}
    for n, r in enumerate(read_jsonl(path), 1):
        if "instance_id" not in r:
            raise SystemExit(f"{path}: row {n} has no instance_id")
        rows[r["instance_id"]] = r
    flagged = {i for i, r in rows.items() if r.get("coupled") is True}
    score = {}
    for i, r in rows.items():
        s = r.get("score")
        s = r.get("p_coupled") if s is None else s
        if isinstance(s, (int, float)) and not isinstance(s, bool) and math.isfinite(s):
            score[i] = float(s)
    return flagged, score


def check_ids(path: Path, flagged: set, score: dict, board_dir: Path, gold: dict) -> tuple[set, dict]:
    """Keep only decided board tasks; warn on ids the board does not hold; stop when none matches."""
    rows = {r["instance_id"] for r in read_jsonl(path)}
    known = {x["instance_id"] for x in read_jsonl(board_dir / "labels.jsonl")}
    unknown, matched = rows - known, rows & set(gold)
    if unknown:
        print(f"warning: {len(unknown)} rows name tasks not on the board (e.g. {sorted(unknown)[0]}); ignored",
              file=sys.stderr)
    if not matched:
        raise SystemExit(f"{path}: no row names a decided board task; check the instance_id values")
    if len(matched) < len(gold):
        print(f"warning: {len(gold) - len(matched)} of {len(gold)} decided tasks have no row (scored as not coupled)",
              file=sys.stderr)
    return {i for i in flagged if i in gold}, {i: s for i, s in score.items() if i in gold}


def rule_top(gold: dict, share: dict, top: float = TOP_SHARE) -> list[str]:
    ids = sorted(gold)
    k = round(top * len(ids))
    return sorted(ids, key=lambda i: (-share[i], i))[:k]


def row(flag: list[str], gold: dict, score: dict | None = None) -> dict:
    ids = sorted(gold)
    hits = sum(gold[i] for i in flag)
    out = {"flagged": len(flag), "hits": hits, "precision": hits / len(flag) if flag else None,
           "precision_wilson": list(wilson(hits, len(flag))) if flag else [None, None],
           "recall": hits / sum(gold.values())}
    if score is not None:
        out["auroc"] = auroc(ids, {i: score.get(i, -1.0) for i in ids}, gold) if score else None
    return out


def agreement(flagged: set, gold: dict, draws=DRAWS, seed=SEED) -> dict:
    """eval_a2.py's primary numbers: kappa with its task bootstrap interval, precision and recall of coupled."""
    ids = sorted(gold)
    pairs = {i: (gold[i], int(i in flagged)) for i in ids}
    ks, skipped = boot(ids, lambda s: kappa([pairs[i] for i in s]), draws, seed)
    lo, hi = ci(ks)
    return {"kappa": kappa(list(pairs.values())), "kappa_lo": lo, "kappa_hi": hi, "kappa_draws_skipped": skipped}


def board(board_dir: Path = BOARD, preds: Path | None = None) -> dict:
    gold, share = load_board(board_dir)
    ids = sorted(gold)
    top = rule_top(gold, share)
    path = preds or board_dir / "predictions" / "a2-g12b.jsonl"
    flagged, gem = check_ids(path, *load_preds(path), board_dir, gold)
    gem_full = {i: gem.get(i, -1.0) for i in ids}
    base = sum(gold.values()) / len(ids)
    return {
        "n_decided": len(ids), "n_coupled": sum(gold.values()), "top_k": len(top),
        "top_k_boundary": [share[top[-1]], share[sorted(ids, key=lambda i: (-share[i], i))[len(top)]]],
        "rule": row(top, gold, share),
        "model": row([i for i in ids if i in flagged], gold, gem),
        "rule_then_model": row([i for i in top if i in flagged], gold),
        "random": {"precision": base, "auroc": auroc(ids, {i: 0.0 for i in ids}, gold)},
        "model_agreement": agreement(flagged, gold),
        "model_scored": sum(i in gem for i in ids),
        "paired_auroc_model_minus_rule": paired_auroc_diff(ids, gold, gem_full, share) if gem else None,
    }


def _f(x, d=2):
    return "" if x is None else f"{x:.{d}f}"


def print_board(b: dict, name: str) -> None:
    print(f"held-out board: {b['n_decided']} decided tasks, {b['n_coupled']} coupled; "
          f"top 20% = {b['top_k']} (rejection share at the cut {b['top_k_boundary'][0]:.4f}, next {b['top_k_boundary'][1]:.4f})")
    print("| auditor | flagged | of them coupled | precision [Wilson 95%] | recall | AUROC |")
    print("|---|---|---|---|---|---|")
    for label, r in ((f"no model: top 20% by SWE-ABS rejection share", b["rule"]), (name, b["model"]),
                     (f"top 20%, then {name} as second read", b["rule_then_model"])):
        lo, hi = r["precision_wilson"]
        print(f"| {label} | {r['flagged']} | {r['hits']} | {_f(r['precision'])} [{_f(lo)}, {_f(hi)}] | "
              f"{_f(r['recall'], 3)} | {_f(r.get('auroc'), 3)} |")
    print(f"| random | | | {_f(b['random']['precision'])} | | {_f(b['random']['auroc'], 1)} |")
    a = b["model_agreement"]
    print(f"{name}: kappa {a['kappa']:.4f} [{a['kappa_lo']:.4f}, {a['kappa_hi']:.4f}] "
          f"(task bootstrap, {DRAWS} draws, seed {SEED}), recall {b['model']['recall']:.4f}")
    d = b["paired_auroc_model_minus_rule"]
    if d:
        print(f"paired AUROC difference, {name} - rule: {d['diff']:.4f} [{d['lo']:.4f}, {d['hi']:.4f}] "
              f"(mean of {d['draws_used']} draws; point estimate {d['point']:.4f}; {b['model_scored']} of "
              f"{b['n_decided']} tasks scored)")
    else:
        print(f"{name}: no score field, so no AUROC")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--preds", type=Path, help="your predictions JSONL (default: Gemma 4 12B, A2)")
    ap.add_argument("--name", help="your auditor's name for the table")
    ap.add_argument("--board", type=Path, default=BOARD, help=argparse.SUPPRESS)
    ap.add_argument("--json", action="store_true", help="print the numbers as JSON instead of the table")
    a = ap.parse_args(argv)
    b = board(a.board, a.preds)
    if a.json:
        print(json.dumps(b, indent=1))
    else:
        print_board(b, a.name or ("your auditor" if a.preds else "Gemma 4 12B, prompted (A2)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
