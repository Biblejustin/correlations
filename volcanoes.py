"""
Volcanoes × {M>=7 quakes, X1+ flares, etc.} correlation tests.

The geophysically interesting test: volcanoes × M>=7 quakes. Both are
subduction-zone phenomena and might genuinely correlate.

Data: data/volcanoes.csv — VEI>=5 catalog 1500-2022.
"""
import argparse
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from scipy import stats

from correlate_events import (
    load_yearly_quakes_m7,
    load_yearly_flares_x1,
    load_yearly_volcanoes,
    load_volcano_dates,
    yearly_corr,
    lag_corr,
)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eq-db-1900", default="../earthquakes/quakes_1900.sqlite")
    ap.add_argument("--eq-db-modern", default="../earthquakes/quakes.sqlite")
    ap.add_argument("--volcanoes-csv", default="data/volcanoes.csv")
    ap.add_argument("--flares-csv", default="data/flares_xclass.csv")
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    volc_5 = load_yearly_volcanoes(args.volcanoes_csv, 1500, 2025, vei_min=5)
    m7 = load_yearly_quakes_m7(args.eq_db_1900, 1900, 2025)
    xf = load_yearly_flares_x1(args.flares_csv, 1976, 2025)

    print("=" * 80)
    print("VOLCANOES (VEI>=5 yearly count) × M>=7 QUAKES (1900-2025)")
    print("=" * 80)
    r = yearly_corr(volc_5, m7, regime_key_a="volcanoes", regime_key_b="quakes_m7")
    print(f"  n={r['n']}")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Raw Spearman rho   : {r['raw_rho']:+.3f}  p={r['raw_p_spear']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    print("\nLag (positive = volcanoes lead quakes):")
    lc = lag_corr(volc_5, m7, range(-10, 11),
                  regime_key_a="volcanoes", regime_key_b="quakes_m7")
    print(lc.to_string(index=False, float_format=lambda v: f"{v:+.3f}" if pd.notna(v) else "nan"))

    print("\n" + "=" * 80)
    print("VOLCANOES × X1+ FLARES (1976-2025)")
    print("=" * 80)
    r = yearly_corr(volc_5, xf, regime_key_a="volcanoes", regime_key_b="flares_x")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    # Daily window: M>=7 within +/- N days of a VEI>=5 eruption
    print("\n" + "=" * 80)
    print("DAILY-WINDOW: M>=7 quakes within +/- N days of VEI>=5 eruption (1965-2025)")
    print("=" * 80)
    volc_dates = load_volcano_dates(args.volcanoes_csv, vei_min=5)
    volc_dates = [d for d in volc_dates if 1965 <= d.year <= 2025]
    print(f"VEI>=5 eruptions 1965-2025 (with month precision): {len(volc_dates)}")

    con = sqlite3.connect(args.eq_db_modern)
    q = pd.read_sql("SELECT time_ms, mag FROM quakes WHERE mag>=7", con)
    q["date"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    q = q[q["date"].dt.year.between(1965, 2025)]
    m7_dates = q["date"].tolist()

    all_dates = set(pd.date_range("1965-01-01", "2025-12-31", freq="D"))
    n_total = len(all_dates)
    n_m7 = len(m7_dates)

    print("\n  window | M>=7 obs | expected | ratio | one-sided binom p")
    print("  " + "-" * 60)
    for w in (7, 30, 90, 180, 365):
        win = set()
        for d in volc_dates:
            for k in range(-w, w + 1):
                win.add(d + pd.Timedelta(days=k))
        win &= all_dates
        n_in = sum(1 for d in m7_dates if d in win)
        expected = n_m7 * len(win) / n_total
        p = stats.binomtest(n_in, n=n_m7, p=len(win)/n_total, alternative="greater").pvalue
        ratio = n_in / expected if expected else float("nan")
        print(f"  ±{w:3d}d  | {n_in:5d}    | {expected:7.2f}  | {ratio:.3f}x | p={p:.3f}")

    fig, axes = plt.subplots(2, 1, figsize=(13, 6), sharex=True)
    ax = axes[0]
    ax.bar(volc_5.index, volc_5.values, color="#aa5522", alpha=0.7)
    ax.set_ylabel("VEI>=5 eruptions/yr")
    ax.set_title("Volcanoes (VEI>=5) × M>=7 quakes (1500-2025)")
    for yr, label in [(1815, "Tambora"), (1883, "Krakatau"), (1912, "Novarupta"),
                       (1991, "Pinatubo"), (2022, "Hunga Tonga")]:
        if yr in volc_5.index:
            ax.annotate(label, (yr, volc_5.loc[yr]),
                        xytext=(0, 8), textcoords="offset points",
                        ha="center", fontsize=8, alpha=0.85)
    ax = axes[1]
    ax.bar(m7.index, m7.values, color="#3355aa", alpha=0.7)
    ax.set_ylabel("M>=7 quakes/yr")
    ax.set_xlabel("Year")
    ax.set_xlim(1500, 2030)
    plt.tight_layout()
    plt.savefig(out / "15_volcanoes_overview.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'15_volcanoes_overview.png'}")


if __name__ == "__main__":
    main()
