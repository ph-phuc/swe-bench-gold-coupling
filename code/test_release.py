"""Tests for the release code (tally rule, census checks, system rates, evaluator, Wilson, verdict view).

    python -m pytest -q code            (from the release root)

The tally, census, system-rate and evaluator tests are the run's own tests, lifted unchanged except for imports and
the spot-check field name; the Wilson, verdict-view and reproduction tests are new for the release.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import audit_tally as A  # noqa: E402
import eval_audit as EV  # noqa: E402
import system_rates  # noqa: E402
import task_verdicts  # noqa: E402
from wilson import wilson  # noqa: E402


def write_jsonl(p: Path, rows) -> None:
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


# --- tally combination rule and census checks ---------------------------------------------------------------

def test_audit_tally_combination_rule(tmp_path):
    assert A.classify("gold_choice", "interface") == "coupled"
    assert A.classify("interface", "in_scope") == "contested"
    assert A.classify("gold_choice", "unclear") == "contested"
    assert A.classify("gold_choice", None) == "coupled_unrefuted"
    assert A.classify("in_scope", "gold_choice") == "in_scope"
    with open(tmp_path / "per_task.csv", "w", encoding="utf-8", newline="") as fh:
        fh.write("instance_id,abs_wbp,unique_abs_wbp\na__a-1,10,8\nb__b-2,5,5\nc__c-3,2,1\n")
    write_jsonl(tmp_path / "handread_near_total.jsonl", [{"instance_id": "a__a-1", "category": "interface"},
                                                         {"instance_id": "b__b-2", "category": "gold_choice"},
                                                         {"instance_id": "c__c-3", "category": "in_scope"}])
    write_jsonl(tmp_path / "refute_round.jsonl", [{"instance_id": "a__a-1", "your_verdict": "gold_choice"},
                                                  {"instance_id": "b__b-2", "your_verdict": "in_scope"}])
    t = A.tally(tmp_path)["handread_near_total.jsonl"]
    assert t["abs_wbp"] == {"coupled": 10, "contested": 5, "in_scope": 2} and t["abs_wbp_total"] == 17
    assert t["unique_abs_wbp"]["coupled"] == 8 and t["contested"] == [["b__b-2", "in_scope"]]


def _census_dir(tmp_path: Path, rest: list[dict], refute_rest: list[dict] | None = None) -> Path:
    """Four tasks with wbp (a, b, c, d) and one without (z); a and b in the first sets, c and d in the census."""
    d = tmp_path / "lt"
    d.mkdir(parents=True)
    rows = [("a", 10), ("b", 5), ("c", 3), ("d", 2), ("z", 0)]
    (d / "per_task.csv").write_text("instance_id,abs_wbp,unique_abs_wbp\n"
                                    + "".join(f"{i},{n},{n}\n" for i, n in rows), encoding="utf-8")
    write_jsonl(d / "handread_near_total.jsonl", [{"instance_id": "a", "category": "gold_choice"}])
    write_jsonl(d / "handread_sample15.jsonl", [{"instance_id": "b", "category": "in_scope"}])
    write_jsonl(d / "refute_round.jsonl", [{"instance_id": "a", "your_verdict": "interface"}])
    write_jsonl(d / "handread_rest.jsonl", rest)
    if refute_rest is not None:
        write_jsonl(d / "refute_rest.jsonl", refute_rest)
    return d


def _rest(c="interface", d="in_scope", kind_d="miss"):
    return [{"instance_id": "c", "category": c, "in_scope_kind": None},
            {"instance_id": "d", "category": d, "in_scope_kind": kind_d}]


def test_census_complete_counts_and_exit_code(tmp_path):
    d = _census_dir(tmp_path, _rest(), [{"instance_id": "c", "your_verdict": "in_scope"}])
    out = A.tally(d)
    c = out["census"]
    assert c["tasks_with_wbp"] == 4 and c["read"] == 4 and c["unread"] == []
    assert c["tasks"] == {"coupled": 1, "in_scope": 2, "contested": 1}
    assert c["abs_wbp"] == {"coupled": 10, "in_scope": 7, "contested": 3}
    assert c["abs_wbp_share"]["coupled"] == round(10 / 20, 4)
    assert out["refuter"] == {"verdicts": 2, "upheld": 1}
    assert A.main(["--dir", str(d), "--require-census"]) == 0


def test_census_incomplete_fails_require_and_hides_share(tmp_path):
    d = _census_dir(tmp_path, _rest())  # c is coupled with no refuter verdict
    assert A.tally(d)["census"]["tasks"]["coupled_unrefuted"] == 1
    assert A.main(["--dir", str(d), "--require-census"]) == 1
    d2 = _census_dir(tmp_path / "x", _rest()[:1], [{"instance_id": "c", "your_verdict": "gold_choice"}])
    c = A.tally(d2)["census"]
    assert c["unread"] == ["d"] and c["abs_wbp_share"] is None
    assert A.main(["--dir", str(d2), "--require-census"]) == 1


@pytest.mark.parametrize("rest, refute_rest", [
    (_rest() + [{"instance_id": "a", "category": "in_scope", "in_scope_kind": "miss"}], None),  # a in two sets
    (_rest(), [{"instance_id": "a", "your_verdict": "in_scope"}]),  # a refuted in two files
    (_rest(), [{"instance_id": "z", "your_verdict": "in_scope"}]),  # stray refuter verdict
    (_rest(kind_d=None), None),  # in_scope without a kind
    ([{"instance_id": "c", "category": "interface"}, _rest()[1]], None),  # census row with no in_scope_kind key
])
def test_census_rejects_inconsistent_inputs(tmp_path, rest, refute_rest):
    with pytest.raises(SystemExit):
        A.tally(_census_dir(tmp_path, rest, refute_rest))


def test_released_census_is_complete():
    assert A.main(["--dir", str(ROOT / "data/census"), "--require-census"]) == 0


# --- system rates (three-task fixture) ----------------------------------------------------------------------

ENTRIES = [
    ("A", "T1", "1", "0"), ("A", "T2", "1", "0"), ("A", "T3", "1", "1"),
    ("B", "T1", "1", "0"), ("B", "T2", "1", "1"), ("B", "T3", "1", "1"),
    ("C", "T1", "1", "0"), ("C", "T3", "0", "0"),
    ("C", "T2", "1", ""),
]


def _write_csv(p: Path, rows: list[dict]) -> None:
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _rates_fixture(d: Path, *, drop_read: str | None = None, bad_system_wbp: bool = False) -> Path:
    long = [{"system": s, "instance_id": t, "sha": "x", "label_official": o, "label_hardened": h, "label_utboost": ""}
            for s, t, o, h in ENTRIES]
    _write_csv(d / "label_long.csv", long)
    wbp, judged = {"T1": 3, "T2": 1, "T3": 0}, {"T1": 3, "T2": 2, "T3": 2}
    _write_csv(d / "per_task.csv", [{"instance_id": t, "abs_wbp": wbp[t], "abs_judged": judged[t]} for t in wbp])
    sys_rows = {"A": (2, 3), "B": (1, 3), "C": (1, 1)}
    _write_csv(d / "per_system.csv", [{"system": s, "tasks": 3, "abs_wbp": w + (bad_system_wbp and s == "A"),
                                       "abs_judged": j} for s, (w, j) in sys_rows.items()])
    reads = {"T1": "gold_choice", "T2": "in_scope"}
    for name in A.CENSUS_SETS:
        (d / name).write_text("", encoding="utf-8")
    write_jsonl(d / A.CENSUS_SETS[0], [{"instance_id": t, "category": c} for t, c in reads.items() if t != drop_read])
    write_jsonl(d / "refute_round.jsonl", [{"instance_id": "T1", "your_verdict": "interface"}])
    census = {"census": {"abs_wbp": {"coupled": 3, "in_scope": 1}, "abs_wbp_total": 4}}
    (d / "audit_tally_census_2026-10-29.json").write_text(json.dumps(census), encoding="utf-8")
    return d


def test_rates_by_group_and_out_dir(tmp_path):
    d = _rates_fixture(tmp_path)
    out = tmp_path / "out"
    assert system_rates.main(["--dir", str(d), "--long", str(d / "label_long.csv"), "--out", str(out),
                              "--draws", "200", "--min-judged", "1"]) == 0
    assert not (d / "per_system_corrected.csv").exists()          # --out keeps the input directory untouched
    with open(out / "per_system_corrected.csv", encoding="utf-8") as fh:
        r = {x["system"]: x for x in csv.DictReader(fh)}
    assert (r["A"]["raw_wbp"], r["A"]["raw_judged"], r["A"]["raw_rate"]) == ("2", "3", "0.6667")
    assert (r["A"]["in_scope_wbp"], r["A"]["in_scope_judged"], r["A"]["in_scope_rate"]) == ("1", "2", "0.5000")
    assert r["A"]["coupled_rate"] == "1.0000" and r["A"]["coupled_share_of_wbp"] == "0.5000"
    assert r["B"]["in_scope_rate"] == "0.0000"
    assert (r["C"]["in_scope_judged"], r["C"]["in_scope_rate"], r["C"]["in_scope_lo"]) == ("0", "", "")
    s = json.loads((out / "per_system_corrected_summary.json").read_text(encoding="utf-8"))
    assert s["wbp_by_group"] == {"raw": 4, "in_scope": 1, "excl_coupled": 1, "coupled": 3, "contested": 0}
    assert s["tasks_by_class"] == {"coupled": 1, "in_scope": 1, "no_wbp": 1}
    assert (r["C"]["ranked"], r["C"]["rank_raw"]) == ("False", "")
    assert (r["A"]["rank_raw"], r["A"]["rank_in_scope"], r["B"]["rank_raw"]) == ("1.0", "1.0", "2.0")


def test_reconciliation_failure_exits(tmp_path):
    d = _rates_fixture(tmp_path, bad_system_wbp=True)
    with pytest.raises(SystemExit, match="reconciliation failed"):
        system_rates.main(["--dir", str(d), "--long", str(d / "label_long.csv"), "--draws", "50"])


def test_unread_task_with_wbp_exits(tmp_path):
    d = _rates_fixture(tmp_path, drop_read="T2")
    with pytest.raises(SystemExit, match="census not usable"):
        system_rates.main(["--dir", str(d), "--long", str(d / "label_long.csv"), "--draws", "50"])


def test_ranks_highest_first_with_ties():
    assert system_rates.ranks(np.array([0.1, 0.3, 0.3, 0.2])).tolist() == [4.0, 1.5, 1.5, 3.0]


# --- Gemma auditor evaluator ----------------------------------------------------------------------------------

def test_coupled_mapping_matches_the_tally():
    assert A.COUPLED == EV.COUPLED == {"interface", "gold_choice"}


def test_kappa_values():
    assert EV.kappa([(1, 1), (0, 0), (1, 1), (0, 0)]) == 1.0
    assert EV.kappa([(1, 1), (0, 1), (1, 1), (0, 1)]) == 0.0
    assert EV.kappa([(1, 1), (1, 1)]) is None
    pairs = [(1, 1)] * 20 + [(1, 0)] * 5 + [(0, 1)] * 10 + [(0, 0)] * 15
    assert abs(EV.kappa(pairs) - 0.4) < 1e-12


def _labels():
    rows = [{"instance_id": f"t{i}", "gold": "coupled" if i < 6 else "genuine", "set": "near_total" if i < 4 else "s"}
            for i in range(10)]
    return rows + [{"instance_id": "c0", "gold": "contested", "set": "s"}]


def _metrics(tmp_path, preds, *extra):
    write_jsonl(tmp_path / "p.jsonl", preds)
    write_jsonl(tmp_path / "l.jsonl", _labels())
    out = subprocess.run([sys.executable, str(HERE / "eval_audit.py"), str(tmp_path / "p.jsonl"),
                          str(tmp_path / "l.jsonl"), *extra], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return dict(line[7:].split("=", 1) for line in out.stdout.splitlines() if line.startswith("METRIC "))


def test_eval_perfect_model_goes_and_missing_rows_block(tmp_path):
    good = [{"instance_id": x["instance_id"], "model": "a", "parse_source": "generated",
             "verdict": "gold_choice" if x["gold"] in ("coupled", "contested") else "in_scope"} for x in _labels()]
    m = _metrics(tmp_path, good + [dict(r, model="b") for r in good[:5]], "--draws", "200")
    assert m["n_decided"] == "10" and m["a.kappa"] == "1.0" and m["a.scale_out_go"] == "1"
    assert m["b.n_missing"] == "5" and m["b.scale_out_go"] == "0" and m["b.share_missing"] == "0.5"


def test_eval_none_verdicts_count_as_not_coupled(tmp_path):
    rows = [{"instance_id": x["instance_id"], "model": "a", "parse_source": "too_long", "verdict": None}
            for x in _labels()]
    m = _metrics(tmp_path, rows, "--draws", "50")
    assert m["a.pred_coupled_share"] == "0.0" and m["a.no_verdict_share"] == "1.0" and m["a.kappa"] == "0.0"


def test_eval_spot_agreement_uses_annotator_field(tmp_path):
    rows = [{"instance_id": x["instance_id"], "model": "a", "parse_source": "generated", "verdict": "interface"}
            for x in _labels()]
    write_jsonl(tmp_path / "s.jsonl", [{"instance_id": "t0", "annotator": "C"}, {"instance_id": "t7", "annotator": "g"},
                                       {"instance_id": "t8", "annotator": "U"}])
    m = _metrics(tmp_path, rows, "--spot", str(tmp_path / "s.jsonl"), "--draws", "50")
    assert m["a.spot_n"] == "2" and m["a.spot_agree"] == "0.5"


# --- release-only helpers -------------------------------------------------------------------------------------

def test_wilson_known_values():
    lo, hi = wilson(8, 10)
    assert (round(lo, 4), round(hi, 4)) == (0.4902, 0.9433)
    lo, hi = wilson(6, 8)
    assert (round(lo, 2), round(hi, 2)) == (0.41, 0.93)
    assert wilson(0, 5)[0] == 0.0 and wilson(5, 5)[1] == 1.0
    with pytest.raises(ValueError):
        wilson(3, 2)


def test_task_verdicts_view_matches_shipped_file():
    built = task_verdicts.build(ROOT / "data/census")
    assert built == (ROOT / "data/task_verdicts.csv").read_text(encoding="utf-8")
    rows = list(csv.DictReader(built.splitlines()))
    assert len(rows) == 305 and {r["class"] for r in rows} == {"coupled", "in_scope", "contested", "env"}
    kinds = [(r["class"], r["kind"]) for r in rows]
    assert kinds.count(("coupled", "1")) == 105 and kinds.count(("coupled", "2")) == 3
    assert all(k == "" for c, k in kinds if c != "coupled")


def test_released_split_is_complete_and_matches_saved_tally():
    import split_tally
    out = split_tally.tally(ROOT / "data/census")
    assert out["complete"] and out == json.loads((ROOT / "data/census/split_tally.json").read_text(encoding="utf-8"))


def test_split_final_class_rule():
    import split_tally
    assert split_tally.final_class(2, {"your_kind": 2}) == "kind2"
    assert split_tally.final_class(2, {"your_kind": 1}) == "kind2_contested"
    assert split_tally.final_class(2, None) == "kind2_contested"
    assert split_tally.final_class(1, None) == "kind1"
    assert split_tally.final_class(1, {"your_kind": 2}) == "kind1_contested"
    assert split_tally.final_class("unclear", None) == "unclear"


def test_spotcheck_kappas_on_known_tables():
    import spotcheck_agreement as SA
    assert SA.cohen(list("CCGG"), list("CCGG"), ["C", "G", "U"]) == 1.0
    assert SA.fleiss([["C", "C"], ["G", "G"]], ["C", "G", "U"]) == 1.0
    assert abs(SA.cohen(list("CCGG"), list("CGCG"), ["C", "G", "U"])) < 1e-12


def test_reproduce_passes():
    out = subprocess.run([sys.executable, str(ROOT / "reproduce.py")], capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
    assert "CHECKS PASS" in out.stdout.splitlines()[-1]
