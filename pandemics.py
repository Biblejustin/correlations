"""
Pandemics × {M>=7 quakes, X1+ flares, wars, famines, floods} correlation tests.

Data: data/pandemics.csv (~36 events from Plague of Athens 430 BC to mpox 2022).
Deaths are spread evenly across [start_year, end_year]; analyses use log10(deaths+1).
"""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from correlate_events import (
    load_yearly_quakes_m7,
    load_yearly_flares_x1,
    load_yearly_pandemic_deaths,
    load_yearly_pandemic_starts,
    load_yearly_war_deaths_active,
    load_yearly_flood_deaths,
    load_yearly_famine_deaths_wpf,
    yearly_corr,
    lag_corr,
)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eq-db-1900", default="../earthquakes/quakes_1900.sqlite")
    ap.add_argument("--pandemics-csv", default="data/pandemics.csv")
    ap.add_argument("--flares-csv", default="data/flares_xclass.csv")
    ap.add_argument("--wars-csv", default="data/wars.csv")
    ap.add_argument("--floods-csv", default="data/floods.csv")
    ap.add_argument("--famines-wpf-csv", default="data/famine_deaths_by_year.csv")
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    pan_log = load_yearly_pandemic_deaths(args.pandemics_csv, 1900, 2025, log10_transform=True)
    pan_starts = load_yearly_pandemic_starts(args.pandemics_csv, 1900, 2025)
    m7 = load_yearly_quakes_m7(args.eq_db_1900, 1900, 2025)
    xf = load_yearly_flares_x1(args.flares_csv, 1976, 2025)

    print("=" * 80)
    print("PANDEMIC DEATHS (log10) × M>=7 QUAKES (1900-2025)")
    print("=" * 80)
    r = yearly_corr(pan_log, m7, regime_key_a="pandemics", regime_key_b="quakes_m7")
    print(f"  n={r['n']}")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Raw Spearman rho   : {r['raw_rho']:+.3f}  p={r['raw_p_spear']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    print("\nLag (positive = pandemics lead quakes):")
    lc = lag_corr(pan_log, m7, range(-10, 11),
                  regime_key_a="pandemics", regime_key_b="quakes_m7")
    print(lc.to_string(index=False, float_format=lambda v: f"{v:+.3f}" if pd.notna(v) else "nan"))

    print("\n" + "=" * 80)
    print("PANDEMIC DEATHS (log10) × X1+ FLARES (1976-2025)")
    print("=" * 80)
    r = yearly_corr(pan_log, xf, regime_key_a="pandemics", regime_key_b="flares_x")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    # Cross-topic
    print("\n" + "=" * 80)
    print("PANDEMIC DEATHS (log10) × WAR DEATHS (log10) (1900-2025)")
    print("=" * 80)
    wars = load_yearly_war_deaths_active(args.wars_csv, 1900, 2025, log10_transform=True)
    r = yearly_corr(pan_log, wars, regime_key_a="pandemics", regime_key_b="wars_global")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    print("\n" + "=" * 80)
    print("PANDEMIC DEATHS (log10) × FLOOD DEATHS (log10) (1900-2025)")
    print("=" * 80)
    floods = load_yearly_flood_deaths(args.floods_csv, 1900, 2025, log10_transform=True)
    r = yearly_corr(pan_log, floods, regime_key_a="pandemics", regime_key_b="floods")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    print("\n" + "=" * 80)
    print("PANDEMIC DEATHS (log10) × WPF FAMINE DEATHS (log10) (1900-2025)")
    print("=" * 80)
    famines = load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, 2025, log10_transform=True)
    r = yearly_corr(pan_log, famines, regime_key_a="pandemics", regime_key_b="famines")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    # Figure
    fig, axes = plt.subplots(2, 1, figsize=(13, 6), sharex=True)
    ax = axes[0]
    ax.fill_between(pan_log.index, 0, pan_log.values, color="#883366", alpha=0.7)
    ax.set_ylabel("log10(pandemic deaths/yr + 1)")
    ax.set_title("Pandemics × M>=7 quakes (1900-2025)")
    # Annotate big events
    for yr, label in [(1918, "Spanish flu"), (1957, "Asian flu"), (1968, "HK flu"),
                       (1981, "HIV/AIDS start"), (2020, "COVID-19")]:
        if yr in pan_log.index and pan_log.loc[yr] > 4:
            ax.annotate(label, (yr, pan_log.loc[yr]),
                        xytext=(0, 5), textcoords="offset points",
                        ha="center", fontsize=9, alpha=0.85)

    ax = axes[1]
    ax.bar(m7.index, m7.values, color="#3355aa", alpha=0.7)
    ax.set_ylabel("M>=7 quakes/yr")
    ax.set_xlabel("Year")
    plt.tight_layout()
    plt.savefig(out / "14_pandemics_overview.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'14_pandemics_overview.png'}")


if __name__ == "__main__":
    main()
