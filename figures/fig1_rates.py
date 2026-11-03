"""Figure 1: per-system SWE-ABS wrong-but-passing rate, raw vs with gold-coupled tasks set aside.

    python figures/fig1_rates.py        (from the release root; needs matplotlib)

Reads data/system_rates/per_system_corrected.csv (ranked systems only, 139) and checks the two
medians it draws against per_system_corrected_summary.json before writing fig1_rates.png (300 dpi) and
fig1_rates.svg next to this script. Colours: the dataviz reference palette's slots 2 (orange, raw) and 1 (blue,
corrected); the pair passes its colour-blind check (protan dE 24.7). Identity is also carried by direct labels.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "data" / "system_rates"
OUT = Path(__file__).resolve().parent
RAW_C, COR_C = "#eb6834", "#2a78d6"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def load() -> list[tuple[float, float]]:
    with open(RES / "per_system_corrected.csv", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["ranked"] == "True"]
    return sorted(((float(r["raw_rate"]), float(r["in_scope_rate"])) for r in rows), reverse=True)


def median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def main() -> int:
    pts = load()
    summ = json.loads((RES / "per_system_corrected_summary.json").read_text(encoding="utf-8"))["ranked"]
    raw_med, cor_med = median([r for r, _ in pts]), median([c for _, c in pts])
    assert len(pts) == 139, len(pts)
    assert round(raw_med, 4) == summ["median_rate_raw"], (raw_med, summ["median_rate_raw"])
    assert round(cor_med, 4) == summ["median_rate_in_scope"], (cor_med, summ["median_rate_in_scope"])

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "svg.fonttype": "none",
                         "svg.hashsalt": "fig1"})  # fixed ids: a rebuild gives the same SVG bytes
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    x = range(1, len(pts) + 1)
    for i, (r, c) in zip(x, pts):
        ax.plot([i, i], [c * 100, r * 100], color=GRID, lw=1.0, zorder=1)
    ax.scatter(list(x), [r * 100 for r, _ in pts], s=9, color=RAW_C, zorder=3, linewidths=0)
    ax.scatter(list(x), [c * 100 for _, c in pts], s=9, color=COR_C, zorder=3, linewidths=0)
    for med, col, label in ((raw_med, RAW_C, "raw"), (cor_med, COR_C, "coupled tasks set aside")):
        ax.axhline(med * 100, color=col, lw=1.0, ls=(0, (4, 3)), zorder=2)
        ax.text(len(pts) + 2, med * 100, f"{label}\nmedian {med * 100:.1f}%", color=INK, va="center",
                ha="left", fontsize=8.5)
    ax.set_xlim(0, len(pts) + 1)
    ax.set_ylim(0, max(r for r, _ in pts) * 100 + 2)
    ax.set_ylabel("share of judged entries rejected (%)", color=MUTED)
    ax.set_xlabel("139 leaderboard systems, ordered by raw rejection rate", color=MUTED)
    ax.set_xticks([])
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right", "bottom"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(MUTED)
    ax.tick_params(colors=MUTED)
    ax.set_title("Setting coupled and contested tasks aside drops the median system's SWE-ABS rejection rate\n"
                 f"from {raw_med * 100:.1f}% to {cor_med * 100:.1f}%", loc="left", fontsize=10, color=INK)
    fig.tight_layout()
    fig.savefig(OUT / "fig1_rates.png", dpi=300, facecolor="white")
    fig.savefig(OUT / "fig1_rates.svg", facecolor="white", metadata={"Date": None})
    print(f"systems {len(pts)}  median raw {raw_med:.4f}  median corrected {cor_med:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
