"""
Overlay all indicator series on the same time axis to ask:
do the 'signs' line up as a single coordinated pattern, or are they independent?

For each indicator, compute the yearly time series in its detection-clean
window, log10-transform death-weighted ones, z-score, and place into a
common 1900-2025 grid (with NaN where the indicator wasn't yet measured).

Plot:
  Top panel  — heatmap: rows = indicators, columns = years, color = z-score
                (red = above the indicator's mean, blue = below)
  Bottom     — 'consensus' line: average z-score across available indicators
                per year, with shaded ± 1 standard error. If all signs
                co-spike, this line jumps. If independent, it flattens out.

Plus a sortable text summary of the top-10 years by consensus z.
"""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from correlate_events import (
    load_yearly_quakes_m7,
    load_yearly_quakes_m8,
    load_yearly_flares_x1,
    load_yearly_war_deaths_split,
    load_yearly_famine_deaths_wpf,
    load_yearly_flood_deaths,
    load_yearly_pandemic_deaths,
    load_yearly_volcanoes,
    load_yearly_cyclone_deaths,
    load_yearly_drought_intensity,
    load_yearly_refugee_displaced,
    load_yearly_economic_crises,
    load_yearly_coups,
    load_yearly_terrorism_deaths,
    load_yearly_stock_drawdown_intensity,
)


def z_score(s):
    """Standardize a pandas Series. Returns NaN where input is NaN."""
    s = s.astype(float)
    mean = np.nanmean(s.values)
    std = np.nanstd(s.values)
    if std == 0 or np.isnan(std):
        return s * np.nan
    return (s - mean) / std


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
    ap.add_argument("--droughts-csv", default="data/droughts.csv")
    ap.add_argument("--refugees-csv", default="data/refugees.csv")
    ap.add_argument("--economic-csv", default="data/economic_crises.csv")
    ap.add_argument("--coups-csv", default="data/coups.csv")
    ap.add_argument("--terrorism-csv", default="data/terrorism.csv")
    ap.add_argument("--crashes-csv", default="data/stock_crashes.csv")
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    # Load each indicator on its detection-clean window
    indicators = [
        ("M>=7 quakes",
            load_yearly_quakes_m7(args.eq_db_1900, 1900, 2025), "geo"),
        ("M>=8 quakes (control)",
            load_yearly_quakes_m8(args.eq_db_1900, 1900, 2025), "geo"),
        ("VEI>=5 eruptions",
            load_yearly_volcanoes(args.volcanoes_csv, 1900, 2025, vei_min=5), "geo"),
        ("X1+ flares",
            load_yearly_flares_x1(args.flares_csv, 1976, 2025), "geo"),
        ("Interstate (basileia) deaths (log10)",
            np.log10(load_yearly_war_deaths_split(args.wars_csv, "interstate", 1900, 2025) + 1),
            "human"),
        ("Intrastate (ethnos) deaths (log10)",
            np.log10(load_yearly_war_deaths_split(args.wars_csv, "intrastate", 1900, 2025) + 1),
            "human"),
        ("Famine deaths (log10)",
            np.log10(load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, 2025) + 1),
            "human"),
        ("Pandemic deaths (log10)",
            np.log10(load_yearly_pandemic_deaths(args.pandemics_csv, 1900, 2025) + 1),
            "human"),
        ("Flood deaths (log10)",
            np.log10(load_yearly_flood_deaths(args.floods_csv, 1985, 2025) + 1),
            "human"),
        ("Cyclone deaths (log10)",
            np.log10(load_yearly_cyclone_deaths(args.cyclones_csv, 1950, 2025) + 1),
            "human"),
        ("Drought intensity (log10)",
            np.log10(load_yearly_drought_intensity(args.droughts_csv, 1850, 2025) + 1),
            "human"),
        ("Refugees displaced (log10)",
            np.log10(load_yearly_refugee_displaced(args.refugees_csv, 1947, 2025) + 1),
            "human"),
        ("Economic crises (all)",
            load_yearly_economic_crises(args.economic_csv, 1800, 2025), "human"),
        ("Coups (all)",
            load_yearly_coups(args.coups_csv, 1950, 2025), "human"),
        ("Terrorism deaths (log10)",
            np.log10(load_yearly_terrorism_deaths(args.terrorism_csv, 1970, 2025) + 1),
            "human"),
        ("Stock crash intensity (log10)",
            np.log10(load_yearly_stock_drawdown_intensity(args.crashes_csv, 1900, 2025) + 1),
            "human"),
    ]

    # Build the common grid 1900-2025
    common_years = np.arange(1900, 2026)
    Z = np.full((len(indicators), len(common_years)), np.nan)
    for i, (name, series, _) in enumerate(indicators):
        z = z_score(series)
        for j, yr in enumerate(common_years):
            if yr in z.index:
                Z[i, j] = z.loc[yr]

    # Consensus row: mean z-score across available indicators per year
    consensus = np.nanmean(Z, axis=0)
    consensus_se = np.nanstd(Z, axis=0) / np.sqrt(np.sum(~np.isnan(Z), axis=0))

    # ---- Figure ----
    fig, axes = plt.subplots(2, 1, figsize=(16, 11),
                                gridspec_kw={"height_ratios": [2.5, 1]}, sharex=True)
    ax = axes[0]
    im = ax.imshow(Z, aspect="auto", cmap="RdBu_r", vmin=-3, vmax=3,
                     extent=[common_years[0] - 0.5, common_years[-1] + 0.5,
                              len(indicators) - 0.5, -0.5],
                     interpolation="nearest")
    ax.set_yticks(range(len(indicators)))
    ax.set_yticklabels([n for n, _, _ in indicators], fontsize=10)
    ax.set_title("Do the signs line up?  Indicator-by-year heatmap (z-scored within each indicator)\n"
                  "Red = above that indicator's normal level for the year; blue = below.  "
                  "Grey = indicator not yet measured in that year.",
                  fontsize=12)
    cbar = plt.colorbar(im, ax=ax, label="z-score (std deviations from indicator mean)",
                          shrink=0.85)

    # Bottom: consensus
    ax = axes[1]
    ax.plot(common_years, consensus, color="#aa3322", linewidth=1.6,
              label="Mean z across indicators")
    ax.fill_between(common_years, consensus - consensus_se,
                       consensus + consensus_se, color="#aa3322", alpha=0.20,
                       label="±1 SE across indicators")
    ax.axhline(0, color="black", linewidth=0.8)
    # Annotate the top years
    notable = {1918: "1918\nWWI+flu", 1943: "1943\nWWII era",
                1970: "1970\nBhola", 1991: "1991\nC22 peak\n+ wars",
                2011: "2011\nTōhoku\n+ Syria", 2013: "2013\nHaiyan\nISIS",
                2023: "2023"}
    for yr, lbl in notable.items():
        if yr in common_years and not np.isnan(consensus[yr - 1900]):
            ax.annotate(lbl, (yr, consensus[yr - 1900]),
                          xytext=(0, 10), textcoords="offset points",
                          ha="center", fontsize=8.5, alpha=0.85)
    ax.set_xlabel("Year")
    ax.set_ylabel("Consensus z")
    ax.set_title("If signs co-spike, this line jumps far above 0. "
                  "If they're independent, it stays near 0 with small wiggle.",
                  fontsize=11)
    ax.set_xlim(common_years[0], common_years[-1])
    ax.set_ylim(-1.5, 2.0)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    plt.savefig(out / "21_signs_overlay.png", dpi=120)
    plt.close()

    # Top years
    df_summary = pd.DataFrame({"year": common_years, "consensus_z": consensus,
                                 "n_indicators": np.sum(~np.isnan(Z), axis=0)})
    df_summary = df_summary.dropna(subset=["consensus_z"])
    top = df_summary.sort_values("consensus_z", ascending=False).head(15)
    print("Top 15 years by cross-indicator consensus z-score:")
    print(top.to_string(index=False))

    # Also: how many indicators were simultaneously above 1 standard deviation?
    above_1 = (Z > 1).sum(axis=0)
    high_years = pd.DataFrame({"year": common_years,
                                 "n_above_1sigma": above_1,
                                 "n_indicators": np.sum(~np.isnan(Z), axis=0)})
    high_years["frac"] = high_years["n_above_1sigma"] / high_years["n_indicators"]
    high_years = high_years.dropna(subset=["n_indicators"])
    high_years = high_years[high_years["n_indicators"] >= 5]
    top_frac = high_years.sort_values("frac", ascending=False).head(15)
    print("\nTop 15 years by fraction of indicators >1 SD above their own mean:")
    print(top_frac.to_string(index=False))

    print(f"\nWrote {out/'21_signs_overlay.png'}")


if __name__ == "__main__":
    main()
