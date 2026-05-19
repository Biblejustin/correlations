"""
Meta-comparison: are trends increasing across indicators?

For each indicator, pull a yearly time series, restrict to the detection-clean
era, and fit OLS slope. Bootstrap 95% CI. Plot all together as a horizontal
bar chart so the question "are things getting worse?" can be answered visually.

We compute two flavors of slope:
  1. Absolute slope per decade (raw events/yr/yr × 10)
  2. Percent-per-decade slope on log scale (exponential growth rate × 100 / decade)

The percent version is the comparable cross-indicator number.

Indicators:
  - M>=7 quakes (1900+, detection-clean)
  - M>=8 quakes (1900+, super-clean control)
  - War onsets (1900+)
  - War deaths (log10, 1900+)
  - WPF famine deaths (1900+)
  - Flood events >=1000 deaths (1950+)
  - Flood deaths log10 (1950+)
  - Pandemic deaths log10 (1900+)
  - VEI>=5 eruptions (1500+, decadal)
  - Cyclones >=1000 deaths (1850+)
  - X1+ flares (1976+) — cyclic, not secular; included for completeness
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
    load_yearly_wars,
    load_yearly_war_deaths_active,
    load_yearly_famine_deaths_wpf,
    load_yearly_flood_events,
    load_yearly_flood_deaths,
    load_yearly_pandemic_deaths,
    load_yearly_volcanoes,
    load_yearly_cyclones,
    load_yearly_cyclone_deaths,
    load_yearly_droughts,
    load_yearly_drought_intensity,
    load_yearly_refugee_displaced,
    load_yearly_economic_crises,
    load_yearly_coups,
    load_yearly_coup_deaths,
)


def fit_slope_bootstrap(years, values, log_scale=False, n_boot=2000, seed=42):
    """Fit OLS slope ± 95% bootstrap CI. If log_scale=True, fit log(y+1) ~ x."""
    rng = np.random.default_rng(seed)
    x = np.asarray(years, dtype=float)
    y = np.asarray(values, dtype=float)
    mask = ~(np.isnan(x) | np.isnan(y))
    x = x[mask]; y = y[mask]
    if log_scale:
        y_fit = np.log10(y + 1)
    else:
        y_fit = y
    slope, intercept = np.polyfit(x, y_fit, 1)
    boots = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(x), len(x))
        s, _ = np.polyfit(x[idx], y_fit[idx], 1)
        boots.append(s)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    # Convert to "per decade"
    return {
        "slope_per_yr": float(slope),
        "slope_per_decade": float(slope * 10),
        "ci_lo_per_decade": float(lo * 10),
        "ci_hi_per_decade": float(hi * 10),
        "mean_value": float(y.mean()),
        "n_years": int(len(x)),
        "log_scale": log_scale,
    }


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
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    # PAIRED-ERA: for each indicator, fit both a "full catalog" trend and a
    # "detection-clean" trend. The two side by side show how much apparent
    # change is detection improvement vs underlying reality.
    #
    # series_specs entries: (group_name, era_label, series, log_scale, category)
    series_specs = [
        # Earthquakes — M>=7 already complete from 1900 so only one era
        ("M>=7 quakes", "1900+ (detection-clean)",
            load_yearly_quakes_m7(args.eq_db_1900, 1900, 2025), False, "geophysical"),
        ("M>=8 quakes", "1900+ (super-clean control)",
            load_yearly_quakes_m8(args.eq_db_1900, 1900, 2025), False, "geophysical"),
        # Volcanoes — show both full catalog and modern-detection era
        ("VEI>=5 eruptions", "1500+ (full catalog)",
            load_yearly_volcanoes(args.volcanoes_csv, 1500, 2025, vei_min=5),
            False, "geophysical"),
        ("VEI>=5 eruptions", "1900+ (modern detection)",
            load_yearly_volcanoes(args.volcanoes_csv, 1900, 2025, vei_min=5),
            False, "geophysical"),
        # X-class flares — only GOES era
        ("X1+ flares", "1976+ (cyclic — not secular)",
            load_yearly_flares_x1(args.flares_csv, 1976, 2025), False, "geophysical"),
        # Wars — onset counts and death-weighted
        ("War onsets", "1900+ (modern conflict records)",
            load_yearly_wars(args.wars_csv, 1900, 2025), False, "human"),
        ("War deaths", "1900+ (modern conflict records)",
            load_yearly_war_deaths_active(args.wars_csv, 1900, 2025, log10_transform=False),
            True, "human"),
        # Famines — full WPF span and post-WWII
        ("WPF famine deaths", "1900+ (early WPF + 20th C)",
            load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, 2025), True, "human"),
        ("WPF famine deaths", "1950+ (post-WWII)",
            load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1950, 2025), True, "human"),
        # Pandemics — full 20th C and post-WHO
        ("Pandemic deaths", "1900+ (germ theory era)",
            load_yearly_pandemic_deaths(args.pandemics_csv, 1900, 2025, log10_transform=False),
            True, "human"),
        ("Pandemic deaths", "1950+ (WHO era)",
            load_yearly_pandemic_deaths(args.pandemics_csv, 1950, 2025, log10_transform=False),
            True, "human"),
        # Floods — full and satellite-era
        ("Flood events >=1000d", "1900+ (full EM-DAT)",
            load_yearly_flood_events(args.floods_csv, 1900, 2025, deaths_min=1000),
            False, "human"),
        ("Flood events >=1000d", "1985+ (satellite era)",
            load_yearly_flood_events(args.floods_csv, 1985, 2025, deaths_min=1000),
            False, "human"),
        ("Flood deaths", "1900+ (full EM-DAT)",
            load_yearly_flood_deaths(args.floods_csv, 1900, 2025), True, "human"),
        ("Flood deaths", "1985+ (satellite era)",
            load_yearly_flood_deaths(args.floods_csv, 1985, 2025), True, "human"),
        # Cyclones — full, aircraft, satellite
        ("Cyclones >=1000d", "1850+ (full catalog)",
            load_yearly_cyclones(args.cyclones_csv, 1850, 2025, deaths_min=1000),
            False, "human"),
        ("Cyclones >=1000d", "1944+ (aircraft recon)",
            load_yearly_cyclones(args.cyclones_csv, 1944, 2025, deaths_min=1000),
            False, "human"),
        ("Cyclones >=1000d", "1979+ (satellite/IBTrACS)",
            load_yearly_cyclones(args.cyclones_csv, 1979, 2025, deaths_min=1000),
            False, "human"),
        ("Cyclone deaths", "1850+ (full catalog)",
            load_yearly_cyclone_deaths(args.cyclones_csv, 1850, 2025), True, "human"),
        ("Cyclone deaths", "1950+ (aircraft+satellite)",
            load_yearly_cyclone_deaths(args.cyclones_csv, 1950, 2025), True, "human"),
        # Droughts — full and satellite era
        ("Active droughts", "1850+ (full catalog)",
            load_yearly_droughts(args.droughts_csv, 1850, 2025, intensity_min=1e5),
            False, "human"),
        ("Active droughts", "1979+ (satellite era)",
            load_yearly_droughts(args.droughts_csv, 1979, 2025, intensity_min=1e5),
            False, "human"),
        ("Drought intensity log10", "1850+ (full catalog)",
            load_yearly_drought_intensity(args.droughts_csv, 1850, 2025), True, "human"),
        ("Drought intensity log10", "1979+ (satellite era)",
            load_yearly_drought_intensity(args.droughts_csv, 1979, 2025), True, "human"),
        # New: refugees / economic crises / coups
        ("Refugees displaced log10", "1947+ (UNHCR era)",
            load_yearly_refugee_displaced(args.refugees_csv, 1947, 2025), True, "human"),
        ("Refugees displaced log10", "1980+ (modern)",
            load_yearly_refugee_displaced(args.refugees_csv, 1980, 2025), True, "human"),
        ("Economic crises (all)", "1800+ (full)",
            load_yearly_economic_crises(args.economic_csv, 1800, 2025), False, "human"),
        ("Economic crises (severe+)", "1913+ (Fed era)",
            load_yearly_economic_crises(args.economic_csv, 1913, 2025, severity_min="severe"),
            False, "human"),
        ("Coups (all)", "1950+ (Powell-Thyne)",
            load_yearly_coups(args.coups_csv, 1950, 2025), False, "human"),
        ("Successful coups", "1950+ (Powell-Thyne)",
            load_yearly_coups(args.coups_csv, 1950, 2025, outcome="successful"),
            False, "human"),
    ]

    results = []
    print(f"{'Group':<22} {'Era':<32} {'slope/dec':>10} {'95% CI':>22} {'mean':>10}")
    print("-" * 105)
    for group, era, series, log_scale, category in series_specs:
        try:
            r = fit_slope_bootstrap(series.index.values, series.values, log_scale=log_scale)
            r["group"] = group
            r["era"] = era
            r["label"] = f"{group} {era}"
            r["category"] = category
            r["log_scale"] = log_scale
            results.append(r)
            ci = f"[{r['ci_lo_per_decade']:+.4f}, {r['ci_hi_per_decade']:+.4f}]"
            print(f"{group:<22} {era:<32} {r['slope_per_decade']:+10.4f} {ci:>22} {r['mean_value']:>10.3f}")
        except Exception as e:
            print(f"{group} {era}: ERROR {e}")

    # Convert slopes to "% per decade" where applicable
    # For log10-scaled slopes: slope_per_decade is in log10 units, multiply by 100*ln(10) = ~230 to get %/decade
    for r in results:
        if r["log_scale"]:
            r["pct_per_decade"] = r["slope_per_decade"] * 100 * np.log(10)
            r["pct_lo"] = r["ci_lo_per_decade"] * 100 * np.log(10)
            r["pct_hi"] = r["ci_hi_per_decade"] * 100 * np.log(10)
        else:
            # For raw count series, express slope as % of mean per decade
            if r["mean_value"] > 0:
                r["pct_per_decade"] = r["slope_per_decade"] / r["mean_value"] * 100
                r["pct_lo"] = r["ci_lo_per_decade"] / r["mean_value"] * 100
                r["pct_hi"] = r["ci_hi_per_decade"] / r["mean_value"] * 100
            else:
                r["pct_per_decade"] = r["pct_lo"] = r["pct_hi"] = 0

    # Group results so eras for the same indicator are adjacent in the chart.
    # Order groups so geophysical baselines come first, then human-system.
    group_order = [
        "M>=7 quakes", "M>=8 quakes", "VEI>=5 eruptions", "X1+ flares",
        "War onsets", "War deaths",
        "WPF famine deaths", "Pandemic deaths",
        "Flood events >=1000d", "Flood deaths",
        "Cyclones >=1000d", "Cyclone deaths",
        "Active droughts", "Drought intensity log10",
        "Refugees displaced log10",
        "Economic crises (all)", "Economic crises (severe+)",
        "Coups (all)", "Successful coups",
    ]
    group_idx = {g: i for i, g in enumerate(group_order)}
    results.sort(key=lambda r: (group_idx.get(r["group"], 99), r["era"]))

    # ---- Horizontal bar chart, paired eras ----
    fig, ax = plt.subplots(figsize=(12, 11))
    y_pos = np.arange(len(results))
    colors = []
    for r in results:
        if r["pct_lo"] > 0:
            colors.append("#cc4422" if r["category"] == "human" else "#dd6633")
        elif r["pct_hi"] < 0:
            colors.append("#22aa44" if r["category"] == "human" else "#44aa66")
        else:
            colors.append("#888888")
    ax.barh(y_pos, [r["pct_per_decade"] for r in results],
             xerr=[[r["pct_per_decade"] - r["pct_lo"] for r in results],
                    [r["pct_hi"] - r["pct_per_decade"] for r in results]],
             color=colors, edgecolor="black", alpha=0.85, capsize=3)
    ax.set_yticks(y_pos)
    ax.set_yticklabels([f"{r['group']} — {r['era']}" for r in results], fontsize=8.5)
    ax.axvline(0, color="black", linewidth=1.0)
    # Shade alternating group bands for visual grouping
    prev_group = None
    band_start = -0.5
    for i, r in enumerate(results):
        if r["group"] != prev_group:
            if prev_group is not None and group_idx.get(prev_group, 0) % 2 == 1:
                ax.axhspan(band_start, i - 0.5, color="#eeeeee", alpha=0.5, zorder=-1)
            band_start = i - 0.5
            prev_group = r["group"]
    # Final band
    if group_idx.get(prev_group, 0) % 2 == 1:
        ax.axhspan(band_start, len(results) - 0.5, color="#eeeeee", alpha=0.5, zorder=-1)

    ax.set_xlabel("Trend (% change per decade, with 95% bootstrap CI)")
    ax.set_title("Is the world getting worse?  Paired-era trend per indicator\n"
                  "Red = increasing & 95% CI excludes 0; Green = decreasing & CI excludes 0; Grey = CI crosses 0")
    for i, r in enumerate(results):
        x = r["pct_per_decade"]
        ax.text(x + (3 if x >= 0 else -3), i,
                  f"{r['pct_per_decade']:+.1f}%",
                  va="center", ha="left" if x >= 0 else "right",
                  fontsize=7.5, alpha=0.85)
    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()
    plt.savefig(out / "19_trends_meta_comparison.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'19_trends_meta_comparison.png'}")

    # Print summary
    print("\n" + "=" * 95)
    print("SUMMARY: trends sorted by direction, 95% CI excludes 0?")
    print("=" * 95)
    increasing = [r for r in results if r["pct_lo"] > 0]
    decreasing = [r for r in results if r["pct_hi"] < 0]
    flat = [r for r in results if r["pct_lo"] <= 0 <= r["pct_hi"]]

    print("\nINCREASING (significant):")
    for r in sorted(increasing, key=lambda r: -r["pct_per_decade"]):
        print(f"  {r['label']:<48} +{r['pct_per_decade']:.1f}%/decade")
    print("\nDECREASING (significant):")
    for r in sorted(decreasing, key=lambda r: r["pct_per_decade"]):
        print(f"  {r['label']:<48} {r['pct_per_decade']:+.1f}%/decade")
    print("\nFLAT (CI crosses 0):")
    for r in flat:
        print(f"  {r['label']:<48} {r['pct_per_decade']:+.1f}%/decade")


if __name__ == "__main__":
    main()
