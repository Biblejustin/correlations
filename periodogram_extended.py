"""
Exploratory annual spectra with fitted AR(1) red-noise sensitivity tests.

Use contiguous observed years, linear detrending, and surrogate searches
of the maximum in the prespecified 9–13-year band and all FFT frequencies.
Each family receives BH adjustment across indicators. Heatmap pointwise
thresholds are visual only. AR(1) tests are conditional approximations,
not source-complete event-process models, solar attribution, or forecasts.
"""
import argparse
import json
import calendar
import sqlite3
from contextlib import closing
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import signal
from statistical_helpers import contiguous_overlap, bh_adjust, last_complete_year

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
    load_yearly_drought_affected,
    load_yearly_refugee_displaced,
    load_yearly_economic_crises,
    load_yearly_coups,
    load_yearly_noaa_quakes,
    load_yearly_noaa_volcanic_events,
    load_yearly_terrorism_deaths,
    load_yearly_stock_drawdown_intensity,
    load_yearly_stock_crashes,
)


def raw_periodogram(x):
    """Linear-detrended annual FFT; reject gaps instead of compressing time."""
    x = np.asarray(x, dtype=float)
    if x.ndim != 1 or not np.isfinite(x).all():
        raise ValueError("Periodogram requires a finite contiguous annual series")
    if len(x) < 4:
        return np.array([]), np.array([])
    x = signal.detrend(x)
    freqs = np.fft.rfftfreq(len(x), d=1.0)
    power = np.abs(np.fft.rfft(x)) ** 2 / len(x)
    return freqs, power


def red_noise_surrogates(x, n_boot=1000, seed=42):
    """Fitted AR(1) red-noise surrogates, conditional on estimated persistence.

    Annual observations have no within-year seasonal cycle to preserve. This
    stationary Gaussian approximation is a sensitivity null for historical
    allocation proxies, not a complete event-process or solar-cause model.
    """
    x = np.asarray(x, dtype=float)
    if len(x) < 8 or not np.isfinite(x).all() or np.std(x) <= 1e-12:
        raise ValueError("Red-noise inference needs eight finite variable annual values")
    x = signal.detrend(x)
    denominator = np.dot(x[:-1], x[:-1])
    phi = float(np.clip(np.dot(x[:-1], x[1:]) / denominator, -0.98, 0.98)) if denominator else 0.0
    innovation_sd = float(np.std(x) * np.sqrt(1 - phi ** 2))
    rng = np.random.default_rng(seed)
    n, burn = len(x), 250
    values = np.zeros((n_boot, n + burn))
    values[:, 0] = rng.normal(0, np.std(x), n_boot)
    noise = rng.normal(0, innovation_sd, (n_boot, n + burn))
    for t in range(1, n + burn):
        values[:, t] = phi * values[:, t-1] + noise[:, t]
    values = signal.detrend(values[:, burn:], axis=1)
    powers = np.abs(np.fft.rfft(values, axis=1)) ** 2 / n
    return powers, phi


def bootstrap_null(x, n_boot=1000, percentile=95, seed=42):
    """Compatibility API: pointwise AR(1) threshold, never selection inference."""
    powers, _ = red_noise_surrogates(x, n_boot, seed)
    return np.percentile(powers, percentile, axis=0)


def spectral_inference(x, band=(9, 13), n_boot=1000, seed=42):
    """Repeat frequency search in every surrogate; expose band/global p-values."""
    freqs, power = raw_periodogram(x)
    null, phi = red_noise_surrogates(x, n_boot, seed)
    expected = np.maximum(null.mean(axis=0), 1e-12)
    ratio = power / expected
    null_ratio = null / expected
    periods = np.divide(1, freqs, out=np.full_like(freqs, np.inf), where=freqs > 0)
    selected = (periods >= band[0]) & (periods <= band[1])
    tested = freqs > 0
    global_max = float(ratio[tested].max())
    global_p = float((1 + np.sum(null_ratio[:, tested].max(axis=1) >= global_max)) / (n_boot + 1))
    if not selected.any():
        peak_period = peak_ratio = band_p = np.nan
    else:
        best = np.flatnonzero(selected)[np.argmax(ratio[selected])]
        peak_period, peak_ratio = float(periods[best]), float(ratio[best])
        band_p = float((1 + np.sum(null_ratio[:, selected].max(axis=1) >= peak_ratio)) / (n_boot + 1))
    return dict(freqs=freqs, power=power, ratio=ratio,
                pointwise_threshold=np.percentile(null, 95, axis=0),
                phi=phi, band_p=band_p, global_p=global_p,
                peak_period=peak_period, peak_ratio=peak_ratio)


def load_sunspot(spaceweather_db, year_lo=1900, year_hi=None):
    year_hi = min(last_complete_year(), last_complete_year() if year_hi is None else year_hi)
    with closing(sqlite3.connect(f"file:{Path(spaceweather_db).resolve()}?mode=ro", uri=True)) as con:
        df = pd.read_sql("SELECT date_iso, sunspot_number FROM silso_daily WHERE sunspot_number >= 0",
                         con, parse_dates=["date_iso"])
    df = df.drop_duplicates("date_iso")
    df["year"] = df["date_iso"].dt.year
    df = df[df.year.between(year_lo, year_hi)]
    result = df.groupby("year")["sunspot_number"].mean().reindex(range(year_lo, year_hi + 1))
    exposure = df.groupby("year").size().reindex(result.index, fill_value=0)
    expected = pd.Series([366 if calendar.isleap(y) else 365 for y in result.index], index=result.index)
    # Mean is an observed-days estimate; at least 95% daily exposure is required.
    return result.where(exposure >= .95 * expected)


def load_g3_days(spaceweather_db, year_lo=1965, year_hi=None):
    year_hi = min(last_complete_year(), last_complete_year() if year_hi is None else year_hi)
    with closing(sqlite3.connect(f"file:{Path(spaceweather_db).resolve()}?mode=ro", uri=True)) as con:
        df = pd.read_sql("""SELECT date_iso, year, kp1,kp2,kp3,kp4,kp5,kp6,kp7,kp8
                            FROM gfz_daily WHERE date_iso BETWEEN ? AND ?""",
                         con, params=(f"{year_lo}-01-01", f"{year_hi}-12-31"), parse_dates=["date_iso"])
    df = df.drop_duplicates("date_iso")
    slots = df[[f"kp{i}" for i in range(1, 9)]]
    valid_day = slots.notna().all(axis=1) & (slots >= 0).all(axis=1) & (slots <= 9).all(axis=1)
    df["g3"] = (slots.max(axis=1) >= 7).astype(float).where(valid_day)
    result = df.groupby("year")["g3"].sum(min_count=1).reindex(range(year_lo, year_hi + 1))
    observed = df.groupby("year")["g3"].count().reindex(result.index, fill_value=0)
    expected = pd.Series([366 if calendar.isleap(y) else 365 for y in result.index], index=result.index)
    # Annual day counts are unknown when any day's eight-slot exposure is missing.
    return result.where(observed == expected)


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
    ap.add_argument("--terrorism-csv", default="data/terrorism.csv")
    ap.add_argument("--crashes-csv", default="data/stock_crashes.csv")
    ap.add_argument("--n-boot", type=int, default=10000)
    ap.add_argument("--year-hi", type=int, default=last_complete_year())
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    missing = [p for p in (args.sw_db, args.eq_db_1900) if not Path(p).exists()]
    if missing:
        print(f"SKIPPED: missing sibling database(s) {missing}; "
              f"run the fetchers in those repos first.")
        return

    # Load each indicator on its detection-clean window (yearly)
    indicators = [
        # Solar
        ("Sunspot number",       load_sunspot(args.sw_db, 1900, args.year_hi),                 "solar"),
        ("G3+ storm days",       load_g3_days(args.sw_db, 1965, args.year_hi),                "solar"),
        ("X1+ flares",           load_yearly_flares_x1(args.flares_csv, 1976, args.year_hi),    "solar"),
        # Earth geophysical
        ("M>=7 quakes",          load_yearly_quakes_m7(args.eq_db_1900, 1900, args.year_hi),    "geo"),
        ("M>=8 quakes",          load_yearly_quakes_m8(args.eq_db_1900, 1900, args.year_hi),    "geo"),
        ("VEI>=5 eruptions",     load_yearly_volcanoes(args.volcanoes_csv, 1900, args.year_hi, vei_min=5), "geo"),
        # Human-system
        ("War onsets",           load_yearly_wars(args.wars_csv, 1900, args.year_hi),           "human"),
        ("War deaths (log10)",   np.log10(load_yearly_war_deaths_active(args.wars_csv, 1900, args.year_hi) + 1), "human"),
        ("Famine deaths (log10)", np.log10(load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, args.year_hi) + 1), "human"),
        ("Pandemic deaths (log10)", np.log10(load_yearly_pandemic_deaths(args.pandemics_csv, 1900, args.year_hi) + 1), "human"),
        ("Flood events >=1000d", load_yearly_flood_events(args.floods_csv, 1900, args.year_hi, deaths_min=1000), "human"),
        ("Flood deaths (log10)", np.log10(load_yearly_flood_deaths(args.floods_csv, 1900, args.year_hi) + 1), "human"),
        ("Cyclone events >=1000d", load_yearly_cyclones(args.cyclones_csv, 1850, args.year_hi, deaths_min=1000), "human"),
        ("Cyclone deaths (log10)", np.log10(load_yearly_cyclone_deaths(args.cyclones_csv, 1850, args.year_hi) + 1), "human"),
        ("Active droughts (1850+)", load_yearly_droughts(args.droughts_csv, 1850, args.year_hi, intensity_min=1e5), "human"),
        ("Drought affected allocation (log10)", np.log10(load_yearly_drought_affected(args.droughts_csv, 1850, args.year_hi) + 1), "human"),
        ("Refugees displaced (log10)", np.log10(load_yearly_refugee_displaced(args.refugees_csv, 1947, args.year_hi) + 1), "human"),
        ("Economic crises (all)", load_yearly_economic_crises(args.economic_csv, 1800, args.year_hi), "human"),
        ("Coups (all)", load_yearly_coups(args.coups_csv, 1950, args.year_hi), "human"),
        ("Terrorism deaths (log10)", np.log10(load_yearly_terrorism_deaths(args.terrorism_csv, 1970, args.year_hi) + 1), "human"),
        ("Stock crash intensity (log10)", np.log10(load_yearly_stock_drawdown_intensity(args.crashes_csv, 1900, args.year_hi) + 1), "human"),
        ("Stock crashes >=20% (count)", load_yearly_stock_crashes(args.crashes_csv, 1900, args.year_hi, drawdown_min=20.0), "human"),
        # Canonical NGDC extended series — long historical span
        ("NGDC M>=7 quakes (1500+)", load_yearly_noaa_quakes(args.noaa_quakes_csv, 1500, 2005, mag_min=7.0), "geo"),
        ("NGDC ≥100-death volcanoes (1500+)", load_yearly_noaa_volcanic_events(args.noaa_volcanoes_csv, 1500, args.year_hi, deaths_min=100), "geo"),
    ]

    common_periods = np.logspace(np.log10(2.5), np.log10(60), 100)
    common_freqs = 1.0 / common_periods

    n_ind = len(indicators)
    M = np.full((n_ind, len(common_freqs)), np.nan)
    band_9_13 = {}  # peak power/null in the 9-13y band per indicator


    rows = []
    for i, (name, series, cat) in enumerate(indicators):
        try:
            observed = contiguous_overlap({"value": series}, min_years=20).value
            result = spectral_inference(observed.to_numpy(), n_boot=args.n_boot)
        except ValueError as exc:
            rows.append(dict(indicator=name, n_years=0, band_p=np.nan, global_p=np.nan, status=str(exc)))
            continue
        f = result["freqs"][1:]
        display_ratio = result["power"][1:] / np.maximum(result["pointwise_threshold"][1:], 1e-12)
        valid = (common_freqs >= f.min()) & (common_freqs <= f.max())
        M[i, valid] = np.interp(common_freqs[valid], f, display_ratio)
        band_9_13[name] = (result["peak_period"], result["peak_ratio"])
        rows.append(dict(indicator=name, n_years=len(observed), start_year=int(observed.index.min()),
                         end_year=int(observed.index.max()), ar1_phi=result["phi"],
                         peak_period=result["peak_period"], peak_ratio=result["peak_ratio"],
                         band_p=result["band_p"], global_p=result["global_p"],
                         band_p_mc_se=float(np.sqrt(result["band_p"] * (1 - result["band_p"]) / (args.n_boot + 1))),
                         n_surrogates=args.n_boot, status="exploratory"))
    inference = pd.DataFrame(rows)
    inference["band_q"] = bh_adjust(inference.band_p)
    inference["global_q"] = bh_adjust(inference.global_p)
    inference.to_csv(out / "23_periodogram_results.csv", index=False)
    (out / "23_periodogram_method.json").write_text(json.dumps({"version": "ar1_maximum_v2", "n_surrogates": args.n_boot, "seed": 42, "band_years": [9, 13], "families": {"band_maxima": len(indicators), "all_frequency_maxima": len(indicators)}, "limitations": ["conditional fitted Gaussian AR1 null", "parameter-estimation uncertainty not integrated", "selected-event catalogs and historical detection changes", "no solar-cause attribution", "annual data contain no within-year seasonal cycle"]}, indent=2))
    print(inference.to_string(index=False))

    # ---- Figure ----
    fig, axes = plt.subplots(2, 1, figsize=(15, 17),
                                gridspec_kw={"height_ratios": [3, 2]})
    ax = axes[0]
    # pcolormesh handles log axis
    pcm = ax.pcolormesh(common_periods, np.arange(n_ind), M,
                          cmap="RdBu_r", vmin=0, vmax=3, shading="auto")
    ax.set_xscale("log")
    ax.set_yticks(range(n_ind))
    ax.set_yticklabels([n for n, _, _ in indicators], fontsize=10)
    ax.invert_yaxis()
    # Reference lines for solar cycles
    for per, lbl in [(11, "11y\nsolar"), (22, "22y\nHale")]:
        ax.axvline(per, color="black", linewidth=0.9, linestyle="--", alpha=0.6)
        ax.text(per, 0.8, lbl, ha="center", va="top", fontsize=9, alpha=0.8)
    cbar = plt.colorbar(pcm, ax=ax, shrink=0.85,
                          label="Power / pointwise AR(1) 95% threshold (visual exploration only)")
    ax.set_xlabel("Period (years, log scale)")
    ax.set_title("Extended periodogram heatmap: do any indicators share the solar 11-year cycle?\n"
                  "Band/global maximum tests and indicator-family BH q-values saved in CSV",
                  fontsize=12)
    ax.set_xlim(2.5, 60)

    # Bottom panel: bar chart of 9-13y band peak power/null per indicator
    ax = axes[1]
    names = [n for n, _, _ in indicators if n in band_9_13]
    ratios = [band_9_13[n][1] for n in names]
    peak_pers = [band_9_13[n][0] for n in names]
    q_by_name = inference.set_index("indicator")["band_q"]
    colors = ["#cc4422" if q_by_name[n] < 0.05 else "#888888" for n in names]
    y_pos = np.arange(len(names))
    ax.barh(y_pos, ratios, color=colors, edgecolor="black", alpha=0.85)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Peak power / expected AR(1) power in 9–13y band")
    ax.set_title("Red = band-maximum test survives BH across indicators; gray = exploratory",
                  fontsize=11)
    for i, (r, pper) in enumerate(zip(ratios, peak_pers)):
        ax.text(r + 0.05, i, f"{pper:.1f}y", va="center", fontsize=8, alpha=0.8)
    plt.tight_layout()
    plt.savefig(out / "23_periodogram_extended.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'23_periodogram_extended.png'}")


if __name__ == "__main__":
    main()
