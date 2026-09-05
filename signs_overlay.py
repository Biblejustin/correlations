"""
Fixed-baseline indicator heatmap and descriptive domain composite v2.

A fixed six-domain panel uses 1985–2010 standardization, equal within-domain
weights, and equal domain weights. M8 is shown only as a control. All fixed
members must be present for eligibility; incomplete years have no headline
score. A mean of input z-scores is not itself a standard normal statistic.
No independence, joint-extreme significance, or fulfillment is inferred.
"""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statistical_helpers import baseline_z_score, domain_composite, last_complete_year, residual_slope_ci

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
    load_yearly_drought_affected,
    load_yearly_refugee_displaced,
    load_yearly_economic_crises,
    load_yearly_coups,
    load_yearly_terrorism_deaths,
    load_yearly_stock_drawdown_intensity,
)


def z_score(s):
    return baseline_z_score(s)


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
    ap.add_argument("--year-hi", type=int, default=last_complete_year())
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    # Load each indicator on its detection-clean window
    indicators = [
        ("M>=7 quakes",
            load_yearly_quakes_m7(args.eq_db_1900, 1900, args.year_hi), "geo"),
        ("M>=8 quakes (control)",
            load_yearly_quakes_m8(args.eq_db_1900, 1900, args.year_hi), "geo"),
        ("VEI>=5 eruptions",
            load_yearly_volcanoes(args.volcanoes_csv, 1900, args.year_hi, vei_min=5), "geo"),
        ("X1+ flares",
            load_yearly_flares_x1(args.flares_csv, 1976, args.year_hi), "geo"),
        ("Interstate (basileia) deaths (log10)",
            np.log10(load_yearly_war_deaths_split(args.wars_csv, "interstate", 1900, args.year_hi) + 1),
            "human"),
        ("Intrastate (ethnos) deaths (log10)",
            np.log10(load_yearly_war_deaths_split(args.wars_csv, "intrastate", 1900, args.year_hi) + 1),
            "human"),
        ("Famine deaths (log10)",
            np.log10(load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, args.year_hi) + 1),
            "human"),
        ("Pandemic deaths (log10)",
            np.log10(load_yearly_pandemic_deaths(args.pandemics_csv, 1900, args.year_hi) + 1),
            "human"),
        ("Flood deaths (log10)",
            np.log10(load_yearly_flood_deaths(args.floods_csv, 1985, args.year_hi) + 1),
            "human"),
        ("Cyclone deaths (log10)",
            np.log10(load_yearly_cyclone_deaths(args.cyclones_csv, 1950, args.year_hi) + 1),
            "human"),
        ("Drought affected-population allocation (log10)",
            np.log10(load_yearly_drought_affected(args.droughts_csv, 1850, args.year_hi) + 1),
            "human"),
        ("Refugees displaced (log10)",
            np.log10(load_yearly_refugee_displaced(args.refugees_csv, 1947, args.year_hi) + 1),
            "human"),
        ("Economic crises (all)",
            load_yearly_economic_crises(args.economic_csv, 1800, args.year_hi), "human"),
        ("Coups (all)",
            load_yearly_coups(args.coups_csv, 1950, args.year_hi), "human"),
        ("Terrorism deaths (log10)",
            np.log10(load_yearly_terrorism_deaths(args.terrorism_csv, 1970, args.year_hi) + 1),
            "human"),
        ("Stock crash intensity (log10)",
            np.log10(load_yearly_stock_drawdown_intensity(args.crashes_csv, 1900, args.year_hi) + 1),
            "human"),
    ]

    # Build the common grid 1900 through requested complete-year cutoff
    common_years = np.arange(1900, args.year_hi + 1)
    standardized, domains, summary = domain_composite(indicators, common_years)
    Z = standardized.to_numpy().T
    consensus = summary.composite.to_numpy()
    summary.to_csv(out / "21_composite.csv")
    domains.to_csv(out / "21_domains.csv", index_label="year")
    (out / "21_composite.json").write_text(json.dumps(summary.attrs, indent=2))
    if not summary.eligible.any():
        print("COMPOSITE UNAVAILABLE: " + summary.attrs["unavailable_reason"])

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
    ax.set_title("Do the signs line up?  Indicator heatmap (fixed 1985–2010 baseline)\n"
                  "Red = above indicator baseline mean; blue = below.  "
                  "Blank = missing observations or insufficient baseline.",
                  fontsize=12)
    cbar = plt.colorbar(im, ax=ax, label="z-score (std deviations from indicator mean)",
                          shrink=0.85)

    # Bottom: consensus
    ax = axes[1]
    ax.plot(common_years, consensus, color="#aa3322", linewidth=1.6,
              label="Equal domain mean, fixed 1985–2010 reference")
    if not summary.eligible.any():
        import textwrap
        ax.text(0.5, 0.65, "Composite unavailable: incomplete fixed panel\n" +
                "\n".join(textwrap.wrap(summary.attrs["unavailable_reason"], 105)),
                transform=ax.transAxes, ha="center", va="center", fontsize=9,
                bbox=dict(facecolor="white", edgecolor="gray", alpha=.95))
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
    ax.set_ylabel("Composite v2 (descriptive)")
    ax.set_title("Descriptive composite v2: all six fixed domains required; M8 control excluded. No significance threshold.",
                  fontsize=11)
    ax.set_xlim(common_years[0], common_years[-1])
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

    high_years = summary.loc[summary.eligible].copy()
    high_years["fraction_domains_above_1"] = high_years.domains_above_1 / high_years.required_domains
    print("\nTop eligible years by fraction of fixed domains above 1 baseline unit (descriptive):")
    print(high_years.sort_values("fraction_domains_above_1", ascending=False).head(15).to_string())

    print(f"\nWrote {out/'21_signs_overlay.png'}")


if __name__ == "__main__":
    main()
