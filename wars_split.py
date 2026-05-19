"""
Wars split by Greek distinction: ethnos vs ethnos (intrastate / ethnic) and
basileia vs basileia (interstate / state-vs-state).

Mt 24:7 / Mk 13:8 / Lk 21:10 doubles the prediction:
  "ἐγερθήσεται γὰρ ἔθνος ἐπὶ ἔθνος, καὶ βασιλεία ἐπὶ βασιλείαν"
  "ethnos against ethnos, and basileia against basileia"

The doubling is exegetically deliberate. Two different kinds of conflict are
named — *both* should rise if the prediction is being fulfilled. Treating
all wars as one bucket can hide the case where one rises while the other
falls.

This script tests each separately:
  - Yearly onset counts, full catalog 1400–2025
  - Decadal counts post-1816 (COW era)
  - Trends per detection-clean era (1816 COW, 1900 modern, 1946 UCDP, 1989 post-Cold-War)
  - Death-weighted version (deaths spread across [start, end])
  - Cross-correlation with famine deaths (the FDR-significant pair, tested for each split)
"""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from correlate_events import (
    load_yearly_wars_split,
    load_yearly_war_deaths_split,
    load_yearly_famine_deaths_wpf,
)
from detection_regimes import REGIMES, piecewise_detrend


def fit_decadal_trend(decades, counts, era_start, partial_decade_start=2020):
    mask = (decades >= era_start) & (decades < partial_decade_start)
    if mask.sum() < 3:
        return None
    x = decades[mask].astype(float); y = counts[mask]
    slope, intercept = np.polyfit(x, y, 1)
    rng = np.random.default_rng(42)
    boots = []
    for _ in range(2000):
        idx = rng.integers(0, len(x), len(x))
        if len(np.unique(x[idx])) < 2:
            continue
        boots.append(np.polyfit(x[idx], y[idx], 1)[0])
    return {"slope": slope, "intercept": intercept,
            "ci_lo": float(np.percentile(boots, 2.5)),
            "ci_hi": float(np.percentile(boots, 97.5)),
            "era_start": era_start}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wars-csv", default="data/wars.csv")
    ap.add_argument("--famines-wpf-csv", default="data/famine_deaths_by_year.csv")
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    inter = load_yearly_wars_split(args.wars_csv, "interstate", 1400, 2025)
    intra = load_yearly_wars_split(args.wars_csv, "intrastate", 1400, 2025)
    inter_d = load_yearly_war_deaths_split(args.wars_csv, "interstate", 1400, 2025, log10_transform=True)
    intra_d = load_yearly_war_deaths_split(args.wars_csv, "intrastate", 1400, 2025, log10_transform=True)
    famines_log = np.log10(load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, 2025) + 1)

    print("=" * 80)
    print("WAR ONSETS, INTERSTATE vs INTRASTATE")
    print("=" * 80)
    eras = [(1400, "Full catalog"), (1816, "COW era"), (1900, "Modern"),
             (1946, "UCDP era"), (1989, "Post-Cold-War")]
    decades_all = np.arange(1400, 2030, 10)
    counts_inter = np.array([(inter.loc[d:d+9]).sum() for d in decades_all])
    counts_intra = np.array([(intra.loc[d:d+9]).sum() for d in decades_all])

    print(f"\n{'Era':<25} {'Inter onsets/dec':>22} {'Intra onsets/dec':>22}")
    print("-" * 75)
    for era, label in eras:
        f_int = fit_decadal_trend(decades_all, counts_inter, era)
        f_intra = fit_decadal_trend(decades_all, counts_intra, era)
        if f_int and f_intra:
            print(f"  {label:<23} ({era}+): "
                  f"{f_int['slope']:+8.3f}/dec [{f_int['ci_lo']:+.3f}, {f_int['ci_hi']:+.3f}]   "
                  f"{f_intra['slope']:+8.3f}/dec [{f_intra['ci_lo']:+.3f}, {f_intra['ci_hi']:+.3f}]")

    # Wars × famines split
    print("\n" + "=" * 80)
    print("WARS↔FAMINES, SPLIT BY WAR TYPE (1900-2025, detrended)")
    print("=" * 80)
    for label, war_series in [("Interstate deaths (log10)", inter_d.loc[1900:2025]),
                                ("Intrastate deaths (log10)", intra_d.loc[1900:2025])]:
        wd = piecewise_detrend(war_series.astype(float), REGIMES["wars_global"])
        fd = piecewise_detrend(famines_log.astype(float), REGIMES["famines"])
        mask = ~(wd.isna() | fd.isna())
        if mask.sum() < 5:
            print(f"  {label}: not enough data")
            continue
        r, p = stats.pearsonr(wd[mask], fd[mask])
        rs, ps = stats.spearmanr(wd[mask], fd[mask])
        print(f"  {label:<32} vs Famine deaths: r = {r:+.3f} (p = {p:.4f}); "
              f"ρ = {rs:+.3f} (p = {ps:.4f})")

    # ---- Figure ----
    fig, axes = plt.subplots(3, 1, figsize=(13, 11), sharex=True)

    # Top: yearly counts of each type (stacked)
    ax = axes[0]
    yrs = np.arange(1400, 2026)
    ax.fill_between(yrs, 0, inter.values, color="#3366aa", alpha=0.75,
                       label=f"basileia (interstate), n={int(inter.sum())}")
    ax.fill_between(yrs, inter.values, inter.values + intra.values,
                       color="#cc4422", alpha=0.75,
                       label=f"ethnos (intrastate), n={int(intra.sum())}")
    ax.set_ylabel("War starts per year")
    ax.set_title("War onsets 1400–2025 by Greek typology: ethnos (intrastate/ethnic) vs basileia (interstate)",
                  fontsize=12)
    ax.legend(loc="upper left", fontsize=10)
    ax.set_xlim(1400, 2030)

    # Middle: decadal counts with trend lines per era
    ax = axes[1]
    width = 4
    ax.bar(decades_all - width/2, counts_inter, width=width, color="#3366aa", alpha=0.8,
            label="basileia (interstate)")
    ax.bar(decades_all + width/2, counts_intra, width=width, color="#cc4422", alpha=0.8,
            label="ethnos (intrastate)")
    # Fit trend lines for the 1900+ era
    for series, label, color, ls in [(counts_inter, "interstate", "#3366aa", "--"),
                                         (counts_intra, "intrastate", "#cc4422", "-.")]:
        f = fit_decadal_trend(decades_all, series, 1900)
        if f:
            line_x = np.linspace(1900, 2020, 50)
            ax.plot(line_x, f["slope"] * line_x + f["intercept"], ls, color=color, linewidth=2,
                      label=f"{label} 1900+: {f['slope']:+.3f}/dec [CI {f['ci_lo']:+.3f}, {f['ci_hi']:+.3f}]")
    ax.set_ylabel("War onsets per decade")
    ax.legend(loc="upper left", fontsize=9)
    ax.set_xlim(1400, 2030)
    ax.set_title("Decadal trends (1900+) — interstate flat-to-falling, intrastate rising")

    # Bottom: death-weighted log10 series side by side
    ax = axes[2]
    ax.fill_between(yrs, 0, inter_d.values, color="#3366aa", alpha=0.5,
                       label="basileia deaths (log10)")
    ax.plot(yrs, intra_d.values, color="#cc4422", linewidth=1.4,
              label="ethnos deaths (log10)")
    ax.set_xlabel("Year")
    ax.set_ylabel("log10(active deaths per year + 1)")
    ax.legend(loc="upper left", fontsize=10)
    ax.set_xlim(1400, 2030)
    ax.set_title("Death-weighted intensity by war type (log scale)")

    plt.tight_layout()
    plt.savefig(out / "27_wars_split_ethnos_basileia.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'27_wars_split_ethnos_basileia.png'}")


if __name__ == "__main__":
    main()
