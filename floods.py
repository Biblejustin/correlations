"""
Floods × {M>=7 quakes, X1+ flares, wars, famines} correlation tests.

Data source: Dartmouth + EM-DAT merged catalog (Biblejustin/flood-data).
Detection-clean band: flood events with >=1000 deaths (117 events 1900-2026).

Tests:
  - Yearly event counts (deaths >= 1000 band) × M>=7 quakes
  - Yearly event counts (deaths >= 1000 band) × X1+ flares
  - Yearly flood deaths (log10, active-spread) × M>=7 quakes
  - Yearly flood deaths (log10, active-spread) × X1+ flares
  - Daily-window test: M>=7 quakes within ±N days of a >=1000-death flood event
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
    load_yearly_flares_x1,
    load_yearly_flood_events,
    load_yearly_flood_deaths,
    load_flood_event_dates,
    load_yearly_wars,
    load_yearly_war_deaths_active,
    load_yearly_famine_deaths_wpf,
    yearly_corr,
    lag_corr,
    event_window_test,
)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eq-db-1900", default="../earthquakes/quakes_1900.sqlite")
    ap.add_argument("--eq-db-modern", default="../earthquakes/quakes.sqlite")
    ap.add_argument("--floods-csv", default="data/floods.csv")
    ap.add_argument("--flares-csv", default="data/flares_xclass.csv")
    ap.add_argument("--wars-csv", default="data/wars.csv")
    ap.add_argument("--famines-wpf-csv", default="data/famine_deaths_by_year.csv")
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    floods_1000 = load_yearly_flood_events(args.floods_csv, 1900, 2025, deaths_min=1000)
    floods_100 = load_yearly_flood_events(args.floods_csv, 1900, 2025, deaths_min=100)
    flood_deaths_lin = load_yearly_flood_deaths(args.floods_csv, 1900, 2025, log10_transform=False)
    flood_deaths_log = load_yearly_flood_deaths(args.floods_csv, 1900, 2025, log10_transform=True)
    m7 = load_yearly_quakes_m7(args.eq_db_1900, 1900, 2025)
    xf = load_yearly_flares_x1(args.flares_csv, 1976, 2025)
    wars = load_yearly_war_deaths_active(args.wars_csv, 1900, 2025, log10_transform=True)
    fam_wpf = load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, 2025, log10_transform=True)

    print(f"Yearly counts of floods >=1000 deaths: n={(floods_1000>0).sum()} non-zero years; "
          f"max={floods_1000.max()}; total events={floods_1000.sum()}")
    print(f"Yearly counts of floods >=100 deaths:  n={(floods_100>0).sum()} non-zero years; max={floods_100.max()}")

    print("\n" + "=" * 80)
    print("FLOODS (>=1000 deaths/yr count) × M>=7 QUAKES (1900-2025)")
    print("=" * 80)
    r = yearly_corr(floods_1000, m7, regime_key_a="floods", regime_key_b="quakes_m7")
    print(f"  n_years            : {r['n']}")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Raw Spearman rho   : {r['raw_rho']:+.3f}  p={r['raw_p_spear']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    print("\nLag (positive = floods lead quakes):")
    lc = lag_corr(floods_1000, m7, range(-10, 11),
                  regime_key_a="floods", regime_key_b="quakes_m7")
    print(lc.to_string(index=False, float_format=lambda v: f"{v:+.3f}" if pd.notna(v) else "nan"))

    print("\n" + "=" * 80)
    print("FLOOD DEATHS (log10) × M>=7 QUAKES (1900-2025)")
    print("=" * 80)
    r = yearly_corr(flood_deaths_log, m7, regime_key_a="floods", regime_key_b="quakes_m7")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Raw Spearman rho   : {r['raw_rho']:+.3f}  p={r['raw_p_spear']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    print("\n" + "=" * 80)
    print("FLOODS (>=1000 deaths/yr count) × X1+ FLARES (1976-2025)")
    print("=" * 80)
    r = yearly_corr(floods_1000, xf, regime_key_a="floods", regime_key_b="flares_x")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Raw Spearman rho   : {r['raw_rho']:+.3f}  p={r['raw_p_spear']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    print("\n" + "=" * 80)
    print("FLOOD DEATHS (log10) × X1+ FLARES (1976-2025)")
    print("=" * 80)
    r = yearly_corr(flood_deaths_log, xf, regime_key_a="floods", regime_key_b="flares_x")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Raw Spearman rho   : {r['raw_rho']:+.3f}  p={r['raw_p_spear']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    # === Cross-topic: floods vs wars/famines ===
    print("\n" + "=" * 80)
    print("FLOOD DEATHS (log10) × WAR DEATHS (log10) (1900-2025)")
    print("=" * 80)
    r = yearly_corr(flood_deaths_log, wars, regime_key_a="floods", regime_key_b="wars_global")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    print("\n" + "=" * 80)
    print("FLOOD DEATHS (log10) × FAMINE DEATHS WPF (log10) (1900-2025)")
    print("=" * 80)
    r = yearly_corr(flood_deaths_log, fam_wpf, regime_key_a="floods", regime_key_b="famines")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    # === Daily window test: M>=7 within +/- N days of major flood ===
    print("\n" + "=" * 80)
    print("DAILY-WINDOW TEST: M>=7 quakes within +/- N days of >=1000-death flood")
    print("=" * 80)
    print("\n(Tsunamis/tidal surges excluded — they are quake-caused and would")
    print(" produce reverse-causation false positives.)")
    flood_dates = load_flood_event_dates(args.floods_csv, deaths_min=1000,
                                          exclude_tsunami=True)
    flood_dates = [d for d in flood_dates if 1965 <= d.year <= 2025]

    # Also report the tsunami-included counterfactual for transparency
    flood_dates_with_tsunami = load_flood_event_dates(args.floods_csv, deaths_min=1000,
                                                       exclude_tsunami=False)
    flood_dates_with_tsunami = [d for d in flood_dates_with_tsunami if 1965 <= d.year <= 2025]

    con = sqlite3.connect(args.eq_db_modern)
    q = pd.read_sql("SELECT time_ms, mag FROM quakes WHERE mag>=7", con)
    q["date"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    q = q[q["date"].dt.year.between(1965, 2025)]
    m7_dates = q["date"].tolist()

    all_dates = set(pd.date_range("1965-01-01", "2025-12-31", freq="D"))
    n_total = len(all_dates)
    n_m7 = len(m7_dates)

    def run_window_test(flood_set, label):
        print(f"\n--- {label} ({len(flood_set)} events) ---")
        print("  window | M>=7 obs | expected | ratio | one-sided binom p")
        print("  " + "-" * 60)
        for w in (0, 1, 3, 7, 14, 30):
            win = set()
            for d in flood_set:
                for k in range(-w, w + 1):
                    win.add(d + pd.Timedelta(days=k))
            win &= all_dates
            n_in = sum(1 for d in m7_dates if d in win)
            expected = n_m7 * len(win) / n_total
            p = stats.binomtest(n_in, n=n_m7, p=len(win)/n_total,
                                alternative="greater").pvalue
            ratio = n_in / expected if expected else float("nan")
            print(f"  ±{w:2d}d   | {n_in:5d}    | {expected:7.2f}  | {ratio:.3f}x | p={p:.3f}")

    run_window_test(set(flood_dates), "TSUNAMI/TIDAL-SURGE EXCLUDED (clean test)")
    run_window_test(set(flood_dates_with_tsunami),
                    "WITH tsunami/tidal-surge included (shows reverse-causation inflation)")

    # ---- Figure ----
    fig, axes = plt.subplots(3, 1, figsize=(13, 8), sharex=True)
    ax = axes[0]
    ax.bar(floods_1000.index, floods_1000.values, color="#225599", alpha=0.7, label=">=1000-death floods/yr")
    ax.set_ylabel("Floods/yr (>=1000 deaths)")
    ax.set_title("Floods × M>=7 quakes × X1+ flares  (1900-2025)")
    ax.legend(loc="upper left", fontsize=9)

    ax = axes[1]
    ax.bar(flood_deaths_log.index, flood_deaths_log.values, color="#66aacc", alpha=0.75,
           label="log10(flood deaths/yr + 1)")
    ax.set_ylabel("log10 deaths")
    ax.legend(loc="upper left", fontsize=9)

    ax = axes[2]
    ax.bar(m7.index, m7.values, color="#3355aa", alpha=0.7, label="M>=7 quakes/yr")
    ax.bar(xf.index, xf.values, color="#ee8833", alpha=0.7, label="X1+ flares/yr (1976+)")
    ax.set_ylabel("Count/yr")
    ax.set_xlabel("Year")
    ax.set_xlim(1895, 2030)
    ax.legend(loc="upper left", fontsize=9)
    plt.tight_layout()
    plt.savefig(out / "13_floods_overview.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'13_floods_overview.png'}")


if __name__ == "__main__":
    main()
