"""
Famines x {M>=7 quakes, X1+ flares} correlation tests.

Same approach as wars.py.
"""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from correlate_events import (
    load_yearly_quakes_m7,
    load_yearly_flares_x1,
    load_yearly_famines,
    yearly_corr,
    lag_corr,
)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eq-db-1900", default="../earthquakes/quakes_1900.sqlite")
    ap.add_argument("--famines-csv", default="data/famines.csv")
    ap.add_argument("--flares-csv", default="data/flares_xclass.csv")
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    famines = load_yearly_famines(args.famines_csv, 1500, 2025)
    m7 = load_yearly_quakes_m7(args.eq_db_1900, 1900, 2025)
    xf = load_yearly_flares_x1(args.flares_csv, 1976, 2025)

    print("=" * 80)
    print("FAMINES × M>=7 QUAKES (1900-2025, overlap)")
    print("=" * 80)
    r = yearly_corr(famines, m7, regime_key_a="famines", regime_key_b="quakes_m7")
    print(f"  n_years            : {r['n']}")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Raw Spearman rho   : {r['raw_rho']:+.3f}  p={r['raw_p_spear']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    print("\nLag correlation (positive lag = famines lead quakes):")
    lc = lag_corr(famines, m7, range(-10, 11),
                  regime_key_a="famines", regime_key_b="quakes_m7")
    print(lc.to_string(index=False, float_format=lambda v: f"{v:+.3f}" if pd.notna(v) else "nan"))

    print("\n" + "=" * 80)
    print("FAMINES × X1+ FLARES (1976-2025, overlap)")
    print("=" * 80)
    r = yearly_corr(famines, xf, regime_key_a="famines", regime_key_b="flares_x")
    print(f"  n_years            : {r['n']}")
    print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
    print(f"  Raw Spearman rho   : {r['raw_rho']:+.3f}  p={r['raw_p_spear']:.3f}")
    print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")

    # ---- Figure ----
    fig, axes = plt.subplots(2, 1, figsize=(12, 6))
    ax = axes[0]
    ax.bar(famines.index, famines.values, color="#995533", alpha=0.7, label="Famines/yr")
    ax.set_xlim(1500, 2030)
    ax.set_ylabel("Famines / yr")
    ax.set_title("Famines × M>=7 quakes (1500-2025)")
    ax.axvspan(1870, 2025, color="lightyellow", alpha=0.3, label="WPF span")
    ax.legend(loc="upper left", fontsize=8)

    ax = axes[1]
    ax.bar(m7.index, m7.values, color="#3355aa", alpha=0.7, label="M>=7 quakes/yr")
    ax.set_xlim(1500, 2030)
    ax.set_xlabel("Year")
    ax.set_ylabel("M>=7 / yr")
    ax.axvspan(1900, 2025, color="lightblue", alpha=0.2, label="USGS complete")
    ax.legend(loc="upper left", fontsize=8)
    plt.tight_layout()
    plt.savefig(out / "07_famines_overview.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'07_famines_overview.png'}")


if __name__ == "__main__":
    main()
