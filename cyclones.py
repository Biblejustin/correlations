"""
Tropical cyclones × {M>=7 quakes, X1+ flares} correlation tests.
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
    load_yearly_cyclones,
    load_yearly_cyclone_deaths,
    load_cyclone_dates,
    yearly_corr,
    lag_corr,
)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eq-db-1900", default="../earthquakes/quakes_1900.sqlite")
    ap.add_argument("--eq-db-modern", default="../earthquakes/quakes.sqlite")
    ap.add_argument("--cyclones-csv", default="data/cyclones.csv")
    ap.add_argument("--flares-csv", default="data/flares_xclass.csv")
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    cyc = load_yearly_cyclones(args.cyclones_csv, 1900, 2025, deaths_min=1000)
    cyc_d = load_yearly_cyclone_deaths(args.cyclones_csv, 1900, 2025, log10_transform=True)
    m7 = load_yearly_quakes_m7(args.eq_db_1900, 1900, 2025)
    xf = load_yearly_flares_x1(args.flares_csv, 1976, 2025)

    print("=" * 80)
    print("CYCLONES (>=1000 deaths/yr count) × M>=7 QUAKES (1900-2025)")
    print("=" * 80)
    r = yearly_corr(cyc, m7, regime_key_a="cyclones", regime_key_b="quakes_m7")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    print("\n" + "=" * 80)
    print("CYCLONE DEATHS (log10) × M>=7 QUAKES")
    print("=" * 80)
    r = yearly_corr(cyc_d, m7, regime_key_a="cyclones", regime_key_b="quakes_m7")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    print("\n" + "=" * 80)
    print("CYCLONE DEATHS (log10) × X1+ FLARES (1976-2025)")
    print("=" * 80)
    r = yearly_corr(cyc_d, xf, regime_key_a="cyclones", regime_key_b="flares_x")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    # Daily-window test
    print("\n" + "=" * 80)
    print("DAILY-WINDOW: M>=7 quakes within +/- N days of major cyclone (1965-2025)")
    print("=" * 80)
    cyc_dates = load_cyclone_dates(args.cyclones_csv, deaths_min=1000)
    cyc_dates = [d for d in cyc_dates if 1965 <= d.year <= 2025]
    print(f"Major cyclones (>=1000 deaths, 1965-2025): {len(cyc_dates)}")

    con = sqlite3.connect(args.eq_db_modern)
    q = pd.read_sql("SELECT time_ms, mag FROM quakes WHERE mag>=7", con)
    q["date"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    q = q[q["date"].dt.year.between(1965, 2025)]
    m7_dates = q["date"].tolist()
    all_dates = set(pd.date_range("1965-01-01", "2025-12-31", freq="D"))
    n_total = len(all_dates); n_m7 = len(m7_dates)

    print("\n  window | M>=7 obs | expected | ratio | one-sided binom p")
    print("  " + "-" * 60)
    for w in (3, 7, 30, 90):
        win = set()
        for d in cyc_dates:
            for k in range(-w, w + 1):
                win.add(d + pd.Timedelta(days=k))
        win &= all_dates
        n_in = sum(1 for d in m7_dates if d in win)
        expected = n_m7 * len(win) / n_total
        p = stats.binomtest(n_in, n=n_m7, p=len(win)/n_total, alternative="greater").pvalue
        ratio = n_in / expected if expected else float("nan")
        print(f"  ±{w:3d}d  | {n_in:5d}    | {expected:7.2f}  | {ratio:.3f}x | p={p:.3f}")

    fig, ax = plt.subplots(figsize=(13, 4))
    ax.bar(cyc_d.index, cyc_d.values, color="#225599", alpha=0.7,
           label="log10(cyclone deaths/yr+1)")
    ax.set_ylabel("log10 deaths")
    ax.set_xlabel("Year")
    ax.set_title("Tropical cyclones — major events 1900-2025 (deaths log10)")
    for yr, label in [(1970, "Bhola"), (1991, "BD cyclone"), (2008, "Nargis"),
                       (2013, "Haiyan")]:
        if yr in cyc_d.index:
            ax.annotate(label, (yr, cyc_d.loc[yr]),
                        xytext=(0, 5), textcoords="offset points",
                        ha="center", fontsize=9, alpha=0.85)
    ax.legend()
    plt.tight_layout()
    plt.savefig(out / "16_cyclones_overview.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'16_cyclones_overview.png'}")


if __name__ == "__main__":
    main()
