"""Agreement of the blind spot-check annotators with each other and with the model verdicts.

Reads data/spotcheck/spotcheck_letters.json, writes data/spotcheck/spotcheck_agreement.json.
Model verdict per task: gold_choice / interface -> C, in_scope -> G (both census readers).
(Release copy: only the paths differ from the run's code.)
"""
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "data/spotcheck/spotcheck_letters.json"
OUT = ROOT / "data/spotcheck/spotcheck_agreement.json"


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def fleiss(rows, cats):
    """rows: list of per-item label lists (same number of raters per item)."""
    n = len(rows[0])
    N = len(rows)
    p_j = {c: sum(r.count(c) for r in rows) / (N * n) for c in cats}
    P_i = [(sum(r.count(c) ** 2 for c in cats) - n) / (n * (n - 1)) for r in rows]
    P_bar = sum(P_i) / N
    P_e = sum(v * v for v in p_j.values())
    return None if P_e == 1 else (P_bar - P_e) / (1 - P_e)


def cohen(a, b, cats):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    return None if pe == 1 else (po - pe) / (1 - pe)


def main():
    d = json.loads(IN.read_text(encoding="utf-8"))
    model = d["model"]
    ann = d["annotators"]
    coupled = [i for i, m in enumerate(model) if m == "C"]
    cats = ["C", "G", "U"]
    out = {"n_tasks": len(model), "n_annotators": len(ann), "per_annotator": {}}
    for name, labs in ann.items():
        agree = sum(x == y for x, y in zip(labs, model))
        conf = sum(labs[i] == "C" for i in coupled)
        ctrl = sum(labs[i] == "G" for i, m in enumerate(model) if m == "G")
        out["per_annotator"][name] = {
            "agree_with_model": agree, "agree_ci": wilson(agree, len(model)),
            "coupled_confirmed": conf, "of_coupled": len(coupled), "coupled_ci": wilson(conf, len(coupled)),
            "controls_caught": ctrl, "kappa_vs_model": round(cohen(labs, model, cats), 3),
        }
    rows = [[ann[a][i] for a in ann] for i in range(len(model))]
    out["fleiss_kappa_humans"] = round(fleiss(rows, cats), 3)
    maj, per_task = [], []
    for i, r in enumerate(rows):
        c = Counter(r)
        top, k = c.most_common(1)[0]
        m = top if k > len(r) / 2 else "tie"
        maj.append(m)
        per_task.append({"task": d["tasks"][i], "model": model[i], "C": c["C"], "G": c["G"], "U": c["U"],
                         "majority": m, "majority_agrees_model": m == model[i]})
    out["per_task"] = per_task
    out["majority_agrees_model"] = sum(t["majority_agrees_model"] for t in per_task)
    out["majority_coupled_confirmed"] = sum(maj[i] == "C" for i in coupled)
    pairs = [cohen(ann[a], ann[b], cats) for ia, a in enumerate(ann) for b in list(ann)[ia + 1:]]
    out["mean_pairwise_cohen_humans"] = round(sum(pairs) / len(pairs), 3)
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "per_task"}, indent=1))
    for t in per_task:
        print(t)


if __name__ == "__main__":
    main()
