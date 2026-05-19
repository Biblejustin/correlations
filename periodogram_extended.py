"""
Extended periodogram across all indicators.

The original figure 04 showed periodograms for sunspot number, G3+ storm days,
and M≥7 quakes — finding the 11-year solar cycle loud in sunspot/G3+ but
absent from M≥7. This extends the same analysis to all human-system
indicators: wars, famines, pandemics, floods, cyclones, plus M≥8 quakes
and VEI≥5 eruptions as additional geophysical controls.

For each indicator:
  1. Take yearly time series in its detection-clean window
  2. Compute raw FFT periodogram (one-sided)
  3. Compute phase-randomized 95% null bound (1000 surrogates)
  4. Compute the ratio observed power / null bound at each period

The heatmap shows that ratio. A cell ≥1.0 means "power at this period exceeds
what chance phase-shuffling would produce" (a real peak). Cells well below 1.0
mean the indicator has no preferred rhythm at that period.

The solar cycle (11y) and Hale magnetic cycle (22y) are marked as reference
lines. If birth-pain coordination existed at any specific period, we'd see a
vertical column of bright red across multiple indicators.
"""
import argparse
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from correlate_events import (
    load_yearly_quakes_m7,
    load_yearly_quakes_m8,
    load_yearly_flares_x1,
    load_yearly_war_deaths_active,
    load_yearly_wars,
    load_yearly_famine_deaths_wpf,
    load_yearly_flood_deaths,
    load_yearly_flood_events,
    load_yearly_pandemic_deaths,
    load_yearly_volcanoes,
    load_yearly_cyclone_deaths,
    load_yearly_cyclones,
    load_yearly_droughts,
    load_yearly_drought_intensity,
    load_yearly_refugee_displaced,
    load_yearly_economic_crises,
    load_yearly_coups,
    load_yearly_noaa_quakes,
    load_yearly_noaa_volcanic_events,
)


def raw_periodogram(x):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 4:
        return np.array([]), np.array([])
    x = x - x.mean()
    n = len(x)
    freqs = np.fft.rfftfreq(n, d=1.0)
    fft = np.fft.rfft(x)
    power = np.abs(fft) ** 2 / n
    return freqs, power


def bootstrap_null(x, n_boot=1000, percentile=95, seed=42):
    """Bootstrap-resample with replacement (destroys time structure).

    This gives the noise-floor "what does periodogram power look like if
    the years were shuffled?" — a meaningful null for peak detection.
    Phase-randomization preserves the spectrum, so it's only useful for
    coherence-style tests, not single-series peak significance.
    """
    rng = np.random.default_rng(seed)
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 4:
        return np.array([])
    n = len(x)
    n_freqs = len(np.fft.rfftfreq(n, d=1.0))
    nulls = np.empty((n_boot, n_freqs))
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        x_boot = x[idx]
        _, p = raw_periodogram(x_boot)
        nulls[i] = p
    return np.percentile(nulls, percentile, axis=0)


def load_sunspot(spaceweather_db, year_lo=1900, year_hi=2025):
    con = sqlite3.connect(spaceweather_db)
    df = pd.read_sql(
        "SELECT date_iso, sunspot_number FROM silso_daily WHERE sunspot_number >= 0",
        con, parse_dates=["date_iso"])
    df["year"] = df["date_iso"].dt.year
    df = df[df["year"].between(year_lo, year_hi)]
    return df.groupby("year")["sunspot_number"].mean()


def load_g3_days(spaceweather_db, year_lo=1965, year_hi=2025):
    con = sqlite3.connect(spaceweather_db)
    df = pd.read_sql(
        """SELECT date_iso, year, kp1,kp2,kp3,kp4,kp5,kp6,kp7,kp8
            FROM gfz_daily WHERE date_iso BETWEEN ? AND ?""",
        con, params=(f"{year_lo}-01-01", f"{year_hi}-12-31"), parse_dates=["date_iso"])
    df["peak_kp"] = df[[f"kp{i}" for i in range(1, 9)]].max(axis=1)
    df["g3"] = (df["peak_kp"] >= 7).astype(int)
    return df.groupby("year")["g3"].sum()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sw-db", default="../spaceweather/spaceweather.sqlite")
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
    ap.add_argument("--noaa-quakes-csv", default="data/noaa_significant_earthquakes.csv")
    ap.add_argument("--noaa-volcanoes-csv", default="data/noaa_volcanic_events.csv")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    # Load each indicator on its detection-clean window (yearly)
    indicators = [
        # Solar
        ("Sunspot number",       load_sunspot(args.sw_db, 1900, 2025),                 "solar"),
        ("G3+ storm days",       load_g3_days(args.sw_db, 1965, 2025),                "solar"),
        ("X1+ flares",           load_yearly_flares_x1(args.flares_csv, 1976, 2025),    "solar"),
        # Earth geophysical
        ("M>=7 quakes",          load_yearly_quakes_m7(args.eq_db_1900, 1900, 2025),    "geo"),
        ("M>=8 quakes",          load_yearly_quakes_m8(args.eq_db_1900, 1900, 2025),    "geo"),
        ("VEI>=5 eruptions",     load_yearly_volcanoes(args.volcanoes_csv, 1900, 2025, vei_min=5), "geo"),
        # Human-system
        ("War onsets",           load_yearly_wars(args.wars_csv, 1900, 2025),           "human"),
        ("War deaths (log10)",   np.log10(load_yearly_war_deaths_active(args.wars_csv, 1900, 2025) + 1), "human"),
        ("Famine deaths (log10)", np.log10(load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, 2025) + 1), "human"),
        ("Pandemic deaths (log10)", np.log10(load_yearly_pandemic_deaths(args.pandemics_csv, 1900, 2025) + 1), "human"),
        ("Flood events >=1000d", load_yearly_flood_events(args.floods_csv, 1900, 2025, deaths_min=1000), "human"),
        ("Flood deaths (log10)", np.log10(load_yearly_flood_deaths(args.floods_csv, 1900, 2025) + 1), "human"),
        ("Cyclone events >=1000d", load_yearly_cyclones(args.cyclones_csv, 1850, 2025, deaths_min=1000), "human"),
        ("Cyclone deaths (log10)", np.log10(load_yearly_cyclone_deaths(args.cyclones_csv, 1850, 2025) + 1), "human"),
        ("Active droughts (1850+)", load_yearly_droughts(args.droughts_csv, 1850, 2025, intensity_min=1e5), "human"),
        ("Drought intensity (log10)", np.log10(load_yearly_drought_intensity(args.droughts_csv, 1850, 2025) + 1), "human"),
        ("Refugees displaced (log10)", np.log10(load_yearly_refugee_displaced(args.refugees_csv, 1947, 2025) + 1), "human"),
        ("Economic crises (all)", load_yearly_economic_crises(args.economic_csv, 1800, 2025), "human"),
        ("Coups (all)", load_yearly_coups(args.coups_csv, 1950, 2025), "human"),
        # Canonical NGDC extended series — long historical span
        ("NGDC M>=7 quakes (1500+)", load_yearly_noaa_quakes(args.noaa_quakes_csv, 1500, 2005, mag_min=7.0), "geo"),
        ("NGDC ≥100-death volcanoes (1500+)", load_yearly_noaa_volcanic_events(args.noaa_volcanoes_csv, 1500, 2025, deaths_min=100), "geo"),
    ]

    common_periods = np.logspace(np.log10(2.5), np.log10(60), 100)
    common_freqs = 1.0 / common_periods

    n_ind = len(indicators)
    M = np.full((n_ind, len(common_freqs)), np.nan)
    band_9_13 = {}  # peak power/null in the 9-13y band per indicator

    print(f"{'Indicator':<28} {'n_yr':>5} {'9-13y band peak period':>25} {'power/null at peak':>22}")
    print("-" * 90)

    for i, (name, series, cat) in enumerate(indicators):
        freqs, power = raw_periodogram(series.dropna().values)
        if len(freqs) < 4:
            continue
        null = bootstrap_null(series.dropna().values, n_boot=args.n_boot)
        # avoid f=0
        f = freqs[1:]
        p = power[1:]
        nl = null[1:]
        ratio = p / np.maximum(nl, 1e-10)
        # interpolate ratio to common freq grid (only where in range)
        valid_lo = common_freqs >= f.min()
        valid_hi = common_freqs <= f.max()
        valid = valid_lo & valid_hi
        M[i, valid] = np.interp(common_freqs[valid], f, ratio)

        # Compute 9-13y band peak
        per = 1.0 / f
        band_mask = (per >= 9) & (per <= 13)
        if band_mask.any():
            idx_peak = np.argmax(p[band_mask] / nl[band_mask])
            peak_per = per[band_mask][idx_peak]
            peak_ratio = (p[band_mask] / nl[band_mask])[idx_peak]
            band_9_13[name] = (peak_per, peak_ratio)
            print(f"{name:<28} {len(series.dropna()):>5} {peak_per:>22.1f}y {peak_ratio:>22.3f}")

    # ---- Figure ----
    fig, axes = plt.subplots(2, 1, figsize=(14, 11),
                                gridspec_kw={"height_ratios": [3, 1]})
    ax = axes[0]
    # pcolormesh handles log axis
    pcm = ax.pcolormesh(common_periods, np.arange(n_ind), M,
                          cmap="RdBu_r", vmin=0, vmax=3, shading="auto")
    ax.set_xscale("log")
    ax.set_yticks(range(n_ind))
    ax.set_yticklabels([n for n, _, _ in indicators], fontsize=10)
    ax.invert_yaxis()
    # Reference lines for solar cycles
    for per, lbl in [(11, "11y\nsolar"), (22, "22y\nHale"), (88, "Gleissberg")]:
        ax.axvline(per, color="black", linewidth=0.9, linestyle="--", alpha=0.6)
        ax.text(per, -0.7, lbl, ha="center", va="top", fontsize=9, alpha=0.8)
    cbar = plt.colorbar(pcm, ax=ax, shrink=0.85,
                          label="Power / phase-randomized 95% null  (≥1 = peak above chance)")
    ax.set_xlabel("Period (years, log scale)")
    ax.set_title("Extended periodogram heatmap: do any indicators share the solar 11-year cycle?\n"
                  "Red ≥ 1.0 = peak above chance for that indicator at that period",
                  fontsize=12)
    ax.set_xlim(2.5, 60)

    # Bottom panel: bar chart of 9-13y band peak power/null per indicator
    ax = axes[1]
    names = [n for n, _, _ in indicators if n in band_9_13]
    ratios = [band_9_13[n][1] for n in names]
    peak_pers = [band_9_13[n][0] for n in names]
    colors = ["#cc4422" if r >= 1.0 else "#888888" for r in ratios]
    y_pos = np.arange(len(names))
    ax.barh(y_pos, ratios, color=colors, edgecolor="black", alpha=0.85)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=9)
    ax.invert_yaxis()
    ax.axvline(1.0, color="black", linewidth=1, linestyle="--",
                  label="null bound = 1.0")
    ax.set_xlabel("Peak power / null in 9-13y band (the solar-cycle window)")
    ax.set_title("How loud is each indicator at the 11-year solar cycle frequency?",
                  fontsize=11)
    ax.legend(loc="upper right", fontsize=9)
    for i, (r, pper) in enumerate(zip(ratios, peak_pers)):
        ax.text(r + 0.05, i, f"{pper:.1f}y", va="center", fontsize=8, alpha=0.8)
    plt.tight_layout()
    plt.savefig(out / "23_periodogram_extended.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'23_periodogram_extended.png'}")


if __name__ == "__main__":
    main()
