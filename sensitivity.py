"""
Descriptive selected-year influence on correlations and annual trend estimates.

Top residual/raw-value years are removed with a complete deletion ledger.
Correlation regime trends are refitted on retained actual years. No iid
post-selection p-values or causal conclusions are reported. Invalid/missing
source coverage remains unavailable. Export JSON/CSV plus figure24.
"""
import argparse
import json
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
from statistical_helpers import contiguous_overlap, last_complete_year


def jackknife_corr(a, b, regime_a, regime_b, drop_top_n_a=0, drop_top_n_b=0):
    """Descriptive selected-year deletion; refit regime trends after deletion.

    Selection uses largest absolute residuals in the original observed overlap.
    No post-selection p-value is validly supplied by ordinary Pearson inference.
    The retained actual year index is used for detrending; no times are imputed.
    """
    unavailable = dict(r=np.nan, p=np.nan, n=0, dropped=[], status="unavailable")
    try:
        frame = contiguous_overlap({"a": a, "b": b}, min_years=8)
    except ValueError as exc:
        return {**unavailable, "status": str(exc)}
    a_d = piecewise_detrend(frame.a, REGIMES.get(regime_a, []))
    b_d = piecewise_detrend(frame.b, REGIMES.get(regime_b, []))
    drop = set(a_d.abs().nlargest(drop_top_n_a).index) | set(b_d.abs().nlargest(drop_top_n_b).index)
    remaining = frame.drop(list(drop))
    a3 = piecewise_detrend(remaining.a, REGIMES.get(regime_a, []))
    b3 = piecewise_detrend(remaining.b, REGIMES.get(regime_b, []))
    if len(remaining) < 5 or min(a3.std(), b3.std()) <= 1e-12:
        return {**unavailable, "n": len(remaining), "dropped": sorted(int(y) for y in drop),
                "status": "insufficient variable retained residuals"}
    return dict(r=float(np.corrcoef(a3, b3)[0, 1]), p=np.nan, n=len(remaining),
                dropped=sorted(int(y) for y in drop),
                start_year=int(frame.index.min()), end_year=int(frame.index.max()),
                status="descriptive after selected-year removal; p not estimated")


def selected_year_slope(series, drop_top_n=0):
    """Descriptive raw slope on actual retained years; no iid inference."""
    unavailable = dict(slope=np.nan, standardized_slope=np.nan, n=0, dropped=[])
    try:
        original = contiguous_overlap({"value": series}, min_years=8).value
    except ValueError:
        return unavailable
    drop = original.abs().nlargest(drop_top_n).index
    retained = original.drop(drop)
    if len(retained) < 5 or np.ptp(retained.index.to_numpy()) == 0:
        return {**unavailable, "n": len(retained), "dropped": list(map(int, drop))}
    slope = float(np.polyfit(retained.index.to_numpy(float), retained.to_numpy(float), 1)[0] * 10)
    scale = float(original.std(ddof=0))
    return dict(slope=slope, standardized_slope=slope / scale if scale > 1e-12 else np.nan,
                n=len(retained), dropped=list(map(int, drop)),
                start_year=int(original.index.min()), end_year=int(original.index.max()))


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
    ap.add_argument("--year-hi", type=int, default=last_complete_year())
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    # ---- Test 1: wars↔famines (exploratory pair) ----
    print("=" * 80)
    print("WARS↔FAMINES sensitivity to top-N tail years")
    print("=" * 80)
    wars = np.log10(load_yearly_war_deaths_active(args.wars_csv, 1900, args.year_hi) + 1)
    famines = np.log10(load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, args.year_hi) + 1)

    drop_levels = [0, 1, 3, 5, 10]
    wars_famines_results = []
    for n in drop_levels:
        r = jackknife_corr(wars, famines, "wars_global", "famines",
                            drop_top_n_a=n, drop_top_n_b=n)
        wars_famines_results.append((n, r))
        print(f"  drop top-{n} on each: r = {r['r']:+.3f}, descriptive; "
              f"n_years = {r['n']}, dropped years = {r['dropped']}")

    # ---- Test 2: meta-trend slopes after dropping top-N ----
    print("\n" + "=" * 80)
    print("META-TREND SLOPES sensitivity to top-N tail years")
    print("=" * 80)

    test_series = [
        ("M>=7 quakes (1900+)",
            load_yearly_quakes_m7(args.eq_db_1900, 1900, args.year_hi), False, "quakes_m7"),
        ("M>=8 quakes (1900+)",
            load_yearly_quakes_m8(args.eq_db_1900, 1900, args.year_hi), False, "quakes_m7"),
        ("VEI>=5 (1900+)",
            load_yearly_volcanoes(args.volcanoes_csv, 1900, args.year_hi, vei_min=5), False, "volcanoes"),
        ("X1+ flares (1976+)",
            load_yearly_flares_x1(args.flares_csv, 1976, args.year_hi), False, "flares_x"),
        ("War deaths log10 (1900+)",
            wars, False, "wars_global"),
        ("Famine deaths log10 (1900+)",
            famines, False, "famines"),
        ("Pandemic deaths log10 (1900+)",
            np.log10(load_yearly_pandemic_deaths(args.pandemics_csv, 1900, args.year_hi) + 1),
            False, "pandemics"),
        ("Cyclone deaths log10 (1950+)",
            np.log10(load_yearly_cyclone_deaths(args.cyclones_csv, 1950, args.year_hi) + 1),
            False, "cyclones"),
    ]

    slope_results = []
    slope_details = []
    for label, series, _, regime_key in test_series:
        row = {"label": label}
        for n in [0, 1, 3, 5]:
            result = selected_year_slope(series, n)
            row[f"slope_drop{n}"] = result["slope"]
            row[f"standardized_drop{n}"] = result["standardized_slope"]
            slope_details.append({"indicator": label, "drop_top_n": n, **result})
        slope_results.append(row)
        print(f"{label}: " + ", ".join(f"drop{n}={row[f'slope_drop{n}']:+.4f}/dec" for n in [0, 1, 3, 5]))
    pd.DataFrame(slope_details).to_json(out / "24_tail_slope_sensitivity.json", orient="records", indent=2)
    pd.DataFrame(slope_results).to_csv(out / "24_tail_slope_sensitivity.csv", index=False)
    pd.DataFrame([{ "drop_top_n_each": n, **result } for n, result in wars_famines_results]).to_json(
        out / "24_tail_correlation_sensitivity.json", orient="records", indent=2)

    # ---- Figure ----
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    ax = axes[0]
    ns_drop = [r[0] for r in wars_famines_results]
    rs = [r[1]["r"] for r in wars_famines_results]
    ax.plot(ns_drop, rs, "o-", color="#cc3322", linewidth=2, markersize=10)
    ax.axhline(0, color="black", linewidth=0.7)
    ax.axhline(rs[0], color="grey", linestyle="--",
                  label=f"Full-sample r = {rs[0]:.3f}")
    ax.set_xlabel("Number of largest-residual years dropped per series")
    ax.set_ylabel("Detrended Pearson r (wars × famines)")
    ax.set_title("War/famine correlation after selected-year removal\n"
                  "Regime trends refitted; descriptive sensitivity only")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    ax = axes[1]
    df = pd.DataFrame(slope_results).set_index("label")
    cols = ["standardized_drop0", "standardized_drop1", "standardized_drop3", "standardized_drop5"]
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
    ax.set_xlabel("Trend slope (original-series SD per decade)")
    ax.set_title("Selected-year sensitivity; original-series scale held fixed")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(axis="x", alpha=0.3)

    plt.tight_layout()
    plt.savefig(out / "24_tail_event_sensitivity.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'24_tail_event_sensitivity.png'}")


if __name__ == "__main__":
    main()
