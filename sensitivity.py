"""
Tail-event sensitivity (BACKLOG #1).

For each reported correlation and trend, recompute after dropping the top-N
single events that contribute the most to either series. Tests whether the
result is genuinely a long-run pattern or driven by a handful of catastrophes
(WWII, 1918 Spanish Flu, 1958 Great Chinese Famine, Sumatra+Tōhoku, etc.).

We jackknife at two levels:
  1. Top-N years per indicator (drop the years where the indicator is highest)
  2. The wars↔famines FDR-significant result specifically

Writes figures/24_tail_event_sensitivity.png with two panels.
"""
import argparse
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from correlate_events import (
    load_yearly_quakes_m7,
    load_yearly_quakes_m8,
    load_yearly_flares_x1,
    load_yearly_war_deaths_active,
    load_yearly_famine_deaths_wpf,
    load_yearly_flood_deaths,
    load_yearly_pandemic_deaths,
    load_yearly_volcanoes,
    load_yearly_cyclone_deaths,
)
from detection_regimes import REGIMES, piecewise_detrend


def jackknife_corr(a, b, regime_a, regime_b, drop_top_n_a=0, drop_top_n_b=0):
    """Drop top-N years (by absolute deviation from mean) from each series, recompute r."""
    overlap = a.index.intersection(b.index)
    a2 = a.loc[overlap].astype(float).copy()
    b2 = b.loc[overlap].astype(float).copy()
    a_d = piecewise_detrend(a2, REGIMES.get(regime_a, []))
    b_d = piecewise_detrend(b2, REGIMES.get(regime_b, []))

    # Identify top-N years to drop based on extreme residual
    drop = set()
    if drop_top_n_a > 0:
        deviation = (a_d - a_d.mean()).abs().sort_values(ascending=False)
        drop.update(deviation.head(drop_top_n_a).index.tolist())
    if drop_top_n_b > 0:
        deviation = (b_d - b_d.mean()).abs().sort_values(ascending=False)
        drop.update(deviation.head(drop_top_n_b).index.tolist())

    a3 = a_d.drop(list(drop), errors="ignore")
    b3 = b_d.drop(list(drop), errors="ignore")
    mask = ~(a3.isna() | b3.isna())
    if mask.sum() < 5:
        return {"r": np.nan, "p": np.nan, "n": 0, "dropped": sorted(drop)}
    r, p = stats.pearsonr(a3[mask], b3[mask])
    return {"r": r, "p": p, "n": int(mask.sum()), "dropped": sorted(drop)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eq-db-1900", default="../earthquakes/quakes_1900.sqlite")
    ap.add_argument("--flares-csv", default="data/flares_xclass.csv")
    ap.add_argument("--wars-csv", default="data/wars.csv")
    ap.add_argument("--floods-csv", default="data/floods.csv")
    ap.add_argument("--famines-wpf-csv", default="data/famine_deaths_by_year.csv")
    ap.add_argument("--pandemics-csv", default="data/pandemics.csv")
    ap.add_argument("--volcanoes-csv", default="data/volcanoes.csv")
    ap.add_argument("--cyclones-csv", default="data/cyclones.csv")
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    # ---- Test 1: wars↔famines (the FDR-significant pair) ----
    print("=" * 80)
    print("WARS↔FAMINES sensitivity to top-N tail events")
    print("=" * 80)
    wars = np.log10(load_yearly_war_deaths_active(args.wars_csv, 1900, 2025) + 1)
    famines = np.log10(load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, 2025) + 1)

    drop_levels = [0, 1, 3, 5, 10]
    wars_famines_results = []
    for n in drop_levels:
        r = jackknife_corr(wars, famines, "wars_global", "famines",
                            drop_top_n_a=n, drop_top_n_b=n)
        wars_famines_results.append((n, r))
        print(f"  drop top-{n} on each: r = {r['r']:+.3f}, p = {r['p']:.4f}, "
              f"n_years = {r['n']}, dropped years = {r['dropped']}")

    # ---- Test 2: meta-trend slopes after dropping top-N ----
    print("\n" + "=" * 80)
    print("META-TREND SLOPES sensitivity to top-N tail events")
    print("=" * 80)

    test_series = [
        ("M>=7 quakes (1900+)",
            load_yearly_quakes_m7(args.eq_db_1900, 1900, 2025), False, "quakes_m7"),
        ("M>=8 quakes (1900+)",
            load_yearly_quakes_m8(args.eq_db_1900, 1900, 2025), False, "quakes_m7"),
        ("VEI>=5 (1900+)",
            load_yearly_volcanoes(args.volcanoes_csv, 1900, 2025, vei_min=5), False, "volcanoes"),
        ("X1+ flares (1976+)",
            load_yearly_flares_x1(args.flares_csv, 1976, 2025), False, "flares_x"),
        ("War deaths log10 (1900+)",
            wars, False, "wars_global"),
        ("Famine deaths log10 (1900+)",
            famines, False, "famines"),
        ("Pandemic deaths log10 (1900+)",
            np.log10(load_yearly_pandemic_deaths(args.pandemics_csv, 1900, 2025) + 1),
            False, "pandemics"),
        ("Cyclone deaths log10 (1950+)",
            np.log10(load_yearly_cyclone_deaths(args.cyclones_csv, 1950, 2025) + 1),
            False, "cyclones"),
    ]

    slope_results = []
    for label, series, _, regime_key in test_series:
        row = {"label": label}
        for n in [0, 1, 3, 5]:
            s = series.dropna().copy()
            if n > 0:
                top_n = s.abs().sort_values(ascending=False).head(n).index
                s = s.drop(top_n)
            x = np.array(s.index, dtype=float)
            y = s.values.astype(float)
            slope, _ = np.polyfit(x, y, 1)
            row[f"slope_drop{n}"] = slope * 10  # per decade
        slope_results.append(row)
        deltas = [row[f"slope_drop{n}"] - row["slope_drop0"] for n in [1, 3, 5]]
        print(f"  {label:<35} drop0={row['slope_drop0']:+.4f}/dec  "
              f"drop1={row['slope_drop1']:+.4f}  drop3={row['slope_drop3']:+.4f}  "
              f"drop5={row['slope_drop5']:+.4f}  (Δ max abs = {max(map(abs, deltas)):.4f})")

    # ---- Figure ----
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    ax = axes[0]
    ns_drop = [r[0] for r in wars_famines_results]
    rs = [r[1]["r"] for r in wars_famines_results]
    ax.plot(ns_drop, rs, "o-", color="#cc3322", linewidth=2, markersize=10)
    ax.axhline(0, color="black", linewidth=0.7)
    ax.axhline(0.434, color="grey", linestyle="--",
                  label=f"Full-sample r = {rs[0]:.3f}")
    ax.set_xlabel("Number of top events dropped per series")
    ax.set_ylabel("Detrended Pearson r (wars × famines)")
    ax.set_title("Robustness of wars↔famines r = +0.43\n"
                  "How fast does the correlation collapse as tail events are removed?")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    ax.set_ylim(-0.1, 0.6)

    ax = axes[1]
    df = pd.DataFrame(slope_results).set_index("label")
    cols = ["slope_drop0", "slope_drop1", "slope_drop3", "slope_drop5"]
    x = np.arange(len(df))
    w = 0.2
    colors = ["#222222", "#993333", "#993333", "#993333"]
    alphas = [1.0, 0.5, 0.7, 0.85]
    labels = ["full", "drop top-1", "drop top-3", "drop top-5"]
    for i, (col, color, alpha, lbl) in enumerate(zip(cols, colors, alphas, labels)):
        ax.barh(x + (i - 1.5) * w, df[col], height=w,
                  color=color, alpha=alpha, edgecolor="black", label=lbl)
    ax.axvline(0, color="black", linewidth=0.7)
    ax.set_yticks(x)
    ax.set_yticklabels(df.index, fontsize=8.5)
    ax.set_xlabel("Trend slope (per decade)")
    ax.set_title("Each indicator's trend before/after dropping top-N years")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(axis="x", alpha=0.3)

    plt.tight_layout()
    plt.savefig(out / "24_tail_event_sensitivity.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'24_tail_event_sensitivity.png'}")


if __name__ == "__main__":
    main()
