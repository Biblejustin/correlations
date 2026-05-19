"""
Wars x {M>=7 quakes, X1+ flares} correlation tests.

Yearly counts of war starts, M>=7 earthquakes, and X1+ solar flares; tests:
  - Pearson + Spearman on full overlap
  - Same after regime-detrending (key result for "is the residual correlated?")
  - Lag correlation -10..+10 years on detrended residuals
"""
import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from correlate_events import (
    load_yearly_quakes_m7,
    load_yearly_flares_x1,
    load_yearly_wars,
    yearly_corr,
    lag_corr,
)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eq-db-1900", default="../earthquakes/quakes_1900.sqlite")
    ap.add_argument("--wars-csv", default="data/wars.csv")
    ap.add_argument("--flares-csv", default="data/flares_xclass.csv")
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    wars = load_yearly_wars(args.wars_csv, 1400, 2025)
    m7 = load_yearly_quakes_m7(args.eq_db_1900, 1900, 2025)
    xf = load_yearly_flares_x1(args.flares_csv, 1976, 2025)

    print("=" * 80)
    print("WARS × M>=7 QUAKES (1900-2025, overlap)")
    print("=" * 80)
    r = yearly_corr(wars, m7, regime_key_a="wars_global", regime_key_b="quakes_m7")
    print(f"  n_years            : {r['n']}")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Raw Spearman rho   : {r['raw_rho']:+.3f}  p={r['raw_p_spear']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    print("\nLag correlation (positive lag = wars lead quakes):")
    lc = lag_corr(wars, m7, range(-10, 11),
                  regime_key_a="wars_global", regime_key_b="quakes_m7")
    print(lc.to_string(index=False, float_format=lambda v: f"{v:+.3f}" if pd.notna(v) else "nan"))

    print("\n" + "=" * 80)
    print("WARS × X1+ FLARES (1976-2025, overlap)")
    print("=" * 80)
    r = yearly_corr(wars, xf, regime_key_a="wars_global", regime_key_b="flares_x")
    print(f"  n_years            : {r['n']}")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Raw Spearman rho   : {r['raw_rho']:+.3f}  p={r['raw_p_spear']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    print("\nLag correlation (positive lag = wars lead flares):")
    lc2 = lag_corr(wars, xf, range(-10, 11),
                   regime_key_a="wars_global", regime_key_b="flares_x")
    print(lc2.to_string(index=False, float_format=lambda v: f"{v:+.3f}" if pd.notna(v) else "nan"))

    # ---- Figure ----
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=False)

    # Long-span wars panel
    ax = axes[0]
    ax.bar(wars.index, wars.values, color="#aa3322", alpha=0.6, label="War starts/year")
    ax.set_xlim(1400, 2030)
    ax.set_ylabel("War start count / yr")
    ax.set_title("Wars × M>=7 quakes × X1+ flares (different completeness eras shown)")
    ax.axvspan(1816, 1946, color="lightyellow", alpha=0.3, label="COW span")
    ax.axvspan(1946, 2025, color="lightblue", alpha=0.2, label="UCDP span")
    ax.legend(loc="upper left", fontsize=8)

    # Quakes panel (1900+)
    ax = axes[1]
    ax.bar(m7.index, m7.values, color="#3355aa", alpha=0.7, label="M>=7 quakes/yr (USGS)")
    ax.set_ylabel("M>=7 quakes / yr")
    ax.set_xlim(1400, 2030)
    ax.axvspan(1900, 2025, color="lightblue", alpha=0.2, label="globally complete")
    ax.legend(loc="upper left", fontsize=8)

    # Flares panel (1976+)
    ax = axes[2]
    ax.bar(xf.index, xf.values, color="#ee8833", alpha=0.7, label="X1+ flares/yr (GOES)")
    ax.set_ylabel("X1+ flares / yr")
    ax.set_xlim(1400, 2030)
    ax.set_xlabel("Year")
    ax.axvspan(1976, 2025, color="lightblue", alpha=0.2, label="GOES era")
    ax.legend(loc="upper left", fontsize=8)

    plt.tight_layout()
    plt.savefig(out / "06_wars_overview.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'06_wars_overview.png'}")


if __name__ == "__main__":
    main()
