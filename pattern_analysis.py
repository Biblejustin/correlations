"""
Exploratory event-pattern diagnostics with explicit timing resolution.

Quake timestamps and flare dates retain within-year spacing. Annual-only
catalogs report occupied-onset-year gaps, never inferred event waits. Gap
trend intervals resample fitted residual blocks, retaining the estimated
trend. Count trends and dispersion remain catalogue-scope diagnostics;
pointwise intervals are not multiplicity-corrected and selected catalogues
cannot establish true global rates. Quake diagnostics include aftershocks.
"""
import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from statistical_helpers import last_complete_year, residual_slope_ci, block_indices, contiguous_overlap
from catalog_coverage import apply_coverage
from correlate_events import load_canonical_flood_events


def fit_quadratic_acceleration(event_years, n_boot=2000, seed=42):
    """Fit cumulative count vs (year - mean_year), return curvature coeff + CI.

    Normalizing the x-axis around its mean stabilizes the polynomial fit and
    makes the c coefficient interpretable as 'curvature per (yr - center)²'.
    """
    rng = np.random.default_rng(seed)
    if len(event_years) < 5:
        return dict(c=np.nan, ci_lo=np.nan, ci_hi=np.nan, n=len(event_years))
    yrs = np.sort(np.asarray(event_years, dtype=float))
    n = np.arange(1, len(yrs) + 1)
    mean_yr = yrs.mean()
    x = yrs - mean_yr
    c_pt, b, a = np.polyfit(x, n, 2)
    boots = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(yrs), len(yrs))
        yrs_b = np.sort(yrs[idx])
        x_b = yrs_b - yrs_b.mean()
        n_b = np.arange(1, len(yrs_b) + 1)
        if len(set(yrs_b)) < 3:
            continue
        c_b, _, _ = np.polyfit(x_b, n_b, 2)
        boots.append(c_b)
    if not boots:
        return dict(c=c_pt, ci_lo=np.nan, ci_hi=np.nan, n=len(yrs))
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return dict(c=float(c_pt), ci_lo=float(lo), ci_hi=float(hi),
                n=int(len(yrs)), center=float(mean_yr))


def fit_gap_trend(event_times, n_boot=2000, seed=42, resolution="timestamp"):
    """Regress true waiting times, or explicitly labelled occupied-year gaps.

    Numeric timestamp inputs use fractional calendar years. Duplicate exact
    timestamps remain distinct events with zero separation. Annual catalogs
    cannot recover within-year waiting times; occupied-year diagnostics are
    deliberately labelled and are not evidence of inter-event acceleration.
    """
    times = np.sort(np.asarray(event_times, dtype=float))
    times = times[np.isfinite(times)]
    if resolution == "year":
        times = np.unique(times)
    elif resolution != "timestamp":
        raise ValueError("resolution must be timestamp or year")
    gaps = np.diff(times)
    slope, lo, hi = residual_slope_ci(np.arange(len(gaps)), gaps, n_boot, seed)
    return dict(slope=slope, ci_lo=lo, ci_hi=hi, n=len(times), n_gaps=len(gaps),
                mean_gap=float(gaps.mean()) if len(gaps) else np.nan,
                resolution=resolution,
                interpretation="inter-event waiting times" if resolution == "timestamp"
                else "inter-onset-year gaps; within-year timing unavailable",
                ci_method="fitted residual circular block bootstrap")


def decimal_year(dates):
    dates = pd.to_datetime(dates, utc=True)
    years = dates.dt.year
    start = pd.to_datetime(years.astype(str) + "-01-01", utc=True)
    end = pd.to_datetime((years + 1).astype(str) + "-01-01", utc=True)
    return years + (dates - start) / (end - start)


def dispersion_index(yearly_counts, n_boot=2000, seed=42):
    """Variance-to-mean ratio of a yearly count series. >1 = clustered."""
    rng = np.random.default_rng(seed)
    y = np.asarray(yearly_counts, dtype=float)
    y = y[np.isfinite(y)]
    if len(y) < 5 or y.mean() == 0:
        return dict(d=np.nan, ci_lo=np.nan, ci_hi=np.nan, n=len(y))
    d_pt = y.var() / y.mean() if y.mean() else np.nan
    boots = []
    for _ in range(n_boot):
        sample = y[block_indices(len(y), rng)]
        if sample.mean() > 0:
            boots.append(sample.var() / sample.mean())
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return dict(d=float(d_pt), ci_lo=float(lo), ci_hi=float(hi), n=len(y))


# ---------- Indicator loaders (returns event_year list and yearly-count series) ----------

def _load_indicator(name, args):
    """Returns (event_times, yearly_counts_series, year_range_label)."""
    year_hi = getattr(args, "year_hi", last_complete_year())
    if name == "M>=7 quakes":
        with closing(sqlite3.connect(f"file:{Path(args.eq_db_1900).resolve()}?mode=ro", uri=True)) as con:
            q = pd.read_sql("SELECT time_ms FROM quakes WHERE mag>=7", con)
        q["year"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.year
        q = q[q["year"].between(1900, year_hi)]
        years = decimal_year(pd.to_datetime(q["time_ms"], unit="ms", utc=True)).tolist()
        yc = q.groupby("year").size().reindex(range(1900, year_hi + 1), fill_value=0)
        return years, yc, f"1900-{year_hi}"
    if name == "M>=8 quakes":
        with closing(sqlite3.connect(f"file:{Path(args.eq_db_1900).resolve()}?mode=ro", uri=True)) as con:
            q = pd.read_sql("SELECT time_ms FROM quakes WHERE mag>=8", con)
        q["year"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.year
        q = q[q["year"].between(1900, year_hi)]
        years = decimal_year(pd.to_datetime(q["time_ms"], unit="ms", utc=True)).tolist()
        yc = q.groupby("year").size().reindex(range(1900, year_hi + 1), fill_value=0)
        return years, yc, f"1900-{year_hi}"
    if name == "VEI>=6 eruptions":
        df = pd.read_csv(args.volcanoes_csv)
        df["vei"] = df["vei"].astype(str).str.extract(r"(\d+)")[0].astype(float)
        df = df[(df["vei"] >= 6) & (df["year"] >= 1500) & (df["year"] <= year_hi)]
        years = df["year"].tolist()
        yc = df.groupby("year").size().reindex(range(1500, year_hi + 1), fill_value=0)
        return years, yc, f"1500-{year_hi}"
    if name == "X1+ flares":
        df = pd.read_csv(args.flares_csv, parse_dates=["date"])
        df["year"] = df["date"].dt.year
        df = df[df["year"].between(1976, year_hi)]
        years = decimal_year(df["date"]).tolist()
        yc = df.groupby("year").size().reindex(range(1976, year_hi + 1), fill_value=0)
        return years, yc, f"1976-{year_hi}"
    if name == "Big wars (>=1M deaths)":
        df = pd.read_csv(args.wars_csv)
        df = df[(df["deaths_estimate"] >= 1_000_000) & (df["start_year"] >= 1500) & (df["start_year"] <= year_hi)]
        years = df["start_year"].tolist()
        yc = df.groupby("start_year").size().reindex(range(1500, year_hi + 1), fill_value=0)
        return years, yc, f"1500-{year_hi}"
    if name == "Big intrastate wars (ethnos, >=100k deaths)":
        df = pd.read_csv(args.wars_csv)
        df = df[(df["war_type"] == "intrastate") & (df["deaths_estimate"] >= 100_000) &
                (df["start_year"] >= 1500) & (df["start_year"] <= year_hi)]
        years = df["start_year"].tolist()
        yc = df.groupby("start_year").size().reindex(range(1500, year_hi + 1), fill_value=0)
        return years, yc, f"1500-{year_hi}"
    if name == "Big interstate wars (basileia, >=100k deaths)":
        df = pd.read_csv(args.wars_csv)
        df = df[(df["war_type"] == "interstate") & (df["deaths_estimate"] >= 100_000) &
                (df["start_year"] >= 1500) & (df["start_year"] <= year_hi)]
        years = df["start_year"].tolist()
        yc = df.groupby("start_year").size().reindex(range(1500, year_hi + 1), fill_value=0)
        return years, yc, f"1500-{year_hi}"
    if name == "Great famines (>=1M deaths)":
        df = pd.read_csv(args.famines_wpf_orig)  # famines_wpf.csv has per-event totals
        df = df[df["wpf_authoritative_mortality_estimate"] >= 1_000_000]
        df = df[(df["year"] >= 1870) & (df["year"] <= year_hi)]
        years = df["year"].tolist()
        yc = df.groupby("year").size().reindex(range(1870, year_hi + 1), fill_value=0)
        return years, yc, f"1870-{year_hi}"
    if name == "Great pandemics (>=1M deaths)":
        df = pd.read_csv(args.pandemics_csv)
        df = df[df["deaths_estimate"] >= 1_000_000]
        df = df[(df["start_year"] >= 1500) & (df["start_year"] <= year_hi)]
        years = df["start_year"].tolist()
        yc = df.groupby("start_year").size().reindex(range(1500, year_hi + 1), fill_value=0)
        return years, yc, f"1500-{year_hi}"
    if name == "Great cyclones (>=10k deaths)":
        df = pd.read_csv(args.cyclones_csv)
        df = df[df["deaths_estimate"] >= 10_000]
        df = df[(df["year"] >= 1700) & (df["year"] <= year_hi)]
        years = df["year"].tolist()
        yc = df.groupby("year").size().reindex(range(1700, year_hi + 1), fill_value=0)
        return years, yc, f"1700-{year_hi}"
    if name == "Major floods (>=1000 deaths)":
        df = load_canonical_flood_events(args.floods_csv)
        df = df[df["deaths"] >= 1000]
        df = df[df["year"].between(1900, year_hi)]
        years = df["year"].astype(int).tolist()
        yc = df.groupby(df["year"].astype(int)).size().reindex(range(1900, year_hi + 1), fill_value=0)
        return years, yc, f"1900-{year_hi}"
    if name == "Major droughts (>=1M affected)":
        df = pd.read_csv(args.droughts_csv)
        df["start_year"] = pd.to_numeric(df["start_year"], errors="coerce")
        df["deaths_estimate"] = pd.to_numeric(df["deaths_estimate"], errors="coerce").fillna(0)
        df["people_affected"] = pd.to_numeric(df["people_affected"], errors="coerce").fillna(0)
        df["intensity"] = df["people_affected"]
        df = df[(df["intensity"] >= 1_000_000) & df["start_year"].between(1850, year_hi)]
        years = df["start_year"].astype(int).tolist()
        yc = df.groupby(df["start_year"].astype(int)).size().reindex(range(1850, year_hi + 1), fill_value=0)
        return years, yc, f"1850-{year_hi}"
    if name == "Major refugee crises (>=1M)":
        df = pd.read_csv(args.refugees_csv)
        df["start_year"] = pd.to_numeric(df["start_year"], errors="coerce")
        df["displaced_estimate"] = pd.to_numeric(df["displaced_estimate"], errors="coerce").fillna(0)
        df = df[(df["displaced_estimate"] >= 1_000_000) & df["start_year"].between(1947, year_hi)]
        years = df["start_year"].astype(int).tolist()
        yc = df.groupby(df["start_year"].astype(int)).size().reindex(range(1947, year_hi + 1), fill_value=0)
        return years, yc, f"1947-{year_hi}"
    if name == "Severe economic crises":
        df = pd.read_csv(args.economic_csv)
        order = {"medium": 0, "severe": 1, "extreme": 2}
        df["sev_rank"] = df["severity"].map(order).fillna(-1)
        df = df[(df["sev_rank"] >= 1) & df["year"].between(1800, year_hi)]
        years = df["year"].astype(int).tolist()
        yc = df.groupby(df["year"].astype(int)).size().reindex(range(1800, year_hi + 1), fill_value=0)
        return years, yc, f"1800-{year_hi}"
    if name == "Successful coups":
        df = pd.read_csv(args.coups_csv)
        df = df[(df["outcome"] == "successful") & df["year"].between(1950, year_hi)]
        years = df["year"].astype(int).tolist()
        yc = df.groupby(df["year"].astype(int)).size().reindex(range(1950, year_hi + 1), fill_value=0)
        return years, yc, f"1950-{year_hi}"
    if name == "NGDC M>=7 (1500+, canonical long-span)":
        df = pd.read_csv(args.noaa_quakes_csv)
        df["eqMagnitude"] = pd.to_numeric(df["eqMagnitude"], errors="coerce")
        df = df[(df["eqMagnitude"] >= 7) & df["year"].between(1500, 2005)]
        years = df["year"].astype(int).tolist()
        yc = df.groupby(df["year"].astype(int)).size().reindex(range(1500, 2006), fill_value=0)
        return years, yc, "1500-2005"
    if name == "NGDC ≥100-death volcanoes (1500+)":
        df = pd.read_csv(args.noaa_volcanoes_csv)
        df["deathsTotal"] = pd.to_numeric(df["deathsTotal"], errors="coerce").fillna(0)
        df = df[(df["deathsTotal"] >= 100) & df["year"].between(1500, year_hi)]
        years = df["year"].astype(int).tolist()
        yc = df.groupby(df["year"].astype(int)).size().reindex(range(1500, year_hi + 1), fill_value=0)
        return years, yc, f"1500-{year_hi}"
    if name == "Mass-casualty terrorism (>=100 deaths/year)":
        df = pd.read_csv(args.terrorism_csv)
        df["year"] = pd.to_numeric(df["year"], errors="coerce")
        df["deaths"] = pd.to_numeric(df["deaths"], errors="coerce").fillna(0)
        df = df[(df["deaths"] >= 100) & df["year"].between(1970, year_hi)]
        # "years" semantics here = list of qualifying years (one per row); yc = same series
        years = df["year"].astype(int).tolist()
        yc = df.set_index("year")["deaths"].reindex(range(1970, year_hi + 1), fill_value=0)
        # For acceleration / clustering we want event-style: each qualifying year is one "event"
        yc = (yc > 0).astype(int)
        return years, yc, f"1970-{year_hi}"
    if name == "Major stock crashes (>=20% drawdown)":
        df = pd.read_csv(args.crashes_csv)
        df["year"] = pd.to_numeric(df["year"], errors="coerce")
        df["pct_drawdown"] = pd.to_numeric(df["pct_drawdown"], errors="coerce").fillna(0)
        df = df[(df["pct_drawdown"] >= 20) & df["year"].between(1900, year_hi)]
        years = df["year"].astype(int).tolist()
        yc = df.groupby(df["year"].astype(int)).size().reindex(range(1900, year_hi + 1), fill_value=0)
        return years, yc, f"1900-{year_hi}"
    raise ValueError(name)


def load_indicator(name, args):
    times, counts, span = _load_indicator(name, args)
    sources = {
        "M>=7 quakes": (args.eq_db_1900, "usgs_quakes"),
        "M>=8 quakes": (args.eq_db_1900, "usgs_quakes"),
        "VEI>=6 eruptions": (args.volcanoes_csv, "volcanoes.csv"),
        "X1+ flares": (args.flares_csv, "flares_xclass.csv"),
        "Big wars (>=1M deaths)": (args.wars_csv, "wars.csv"),
        "Big intrastate wars (ethnos, >=100k deaths)": (args.wars_csv, "wars.csv"),
        "Big interstate wars (basileia, >=100k deaths)": (args.wars_csv, "wars.csv"),
        "Great famines (>=1M deaths)": (args.famines_wpf_orig, "famines_wpf.csv"),
        "Great pandemics (>=1M deaths)": (args.pandemics_csv, "pandemics.csv"),
        "Great cyclones (>=10k deaths)": (args.cyclones_csv, "cyclones.csv"),
        "Major floods (>=1000 deaths)": (args.floods_csv, "floods.csv"),
        "Major droughts (>=1M affected)": (args.droughts_csv, "droughts.csv"),
        "Major refugee crises (>=1M)": (args.refugees_csv, "refugees.csv"),
        "Severe economic crises": (args.economic_csv, "economic_crises.csv"),
        "Successful coups": (args.coups_csv, "coups.csv"),
        "NGDC M>=7 (1500+, canonical long-span)": (args.noaa_quakes_csv, "noaa_significant_earthquakes.csv"),
        "NGDC ≥100-death volcanoes (1500+)": (args.noaa_volcanoes_csv, "noaa_volcanic_events.csv"),
        "Mass-casualty terrorism (>=100 deaths/year)": (args.terrorism_csv, "terrorism.csv"),
        "Major stock crashes (>=20% drawdown)": (args.crashes_csv, "stock_crashes.csv"),
    }
    counts = apply_coverage(counts, *sources[name])
    counts = contiguous_overlap({"count": counts}, min_years=5)["count"]
    times = [t for t in times if int(np.floor(t)) in counts.index]
    return times, counts, f"{counts.index.min()}–{counts.index.max()}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eq-db-1900", default="../earthquakes/quakes_1900.sqlite")
    ap.add_argument("--flares-csv", default="data/flares_xclass.csv")
    ap.add_argument("--wars-csv", default="data/wars.csv")
    ap.add_argument("--floods-csv", default="data/floods.csv")
    ap.add_argument("--famines-wpf-orig", default="data/famines_wpf.csv")
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
    ap.add_argument("--year-hi", type=int, default=last_complete_year())
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    indicators = [
        "M>=7 quakes", "M>=8 quakes", "VEI>=6 eruptions", "X1+ flares",
        "Big wars (>=1M deaths)",
        "Big interstate wars (basileia, >=100k deaths)",
        "Big intrastate wars (ethnos, >=100k deaths)",
        "Great famines (>=1M deaths)",
        "Great pandemics (>=1M deaths)", "Great cyclones (>=10k deaths)",
        "Major floods (>=1000 deaths)", "Major droughts (>=1M affected)",
        "Major refugee crises (>=1M)", "Severe economic crises",
        "Successful coups",
        "NGDC M>=7 (1500+, canonical long-span)",
        "NGDC ≥100-death volcanoes (1500+)",
        "Mass-casualty terrorism (>=100 deaths/year)",
        "Major stock crashes (>=20% drawdown)",
    ]

    results = []
    print(f"{'Indicator':<35} {'n':>4} {'curvature c (CI)':>32} {'gap slope (CI)':>30} {'dispersion (CI)':>22}")
    print("-" * 130)
    for ind in indicators:
        years, yc, span = load_indicator(ind, args)
        accel = fit_quadratic_acceleration(years, n_boot=args.n_boot)
        resolution = "timestamp" if ind in ("M>=7 quakes", "M>=8 quakes", "X1+ flares") else "year"
        gaps = fit_gap_trend(years, n_boot=args.n_boot, resolution=resolution)
        disp = dispersion_index(yc.values, n_boot=args.n_boot)
        rate_slope, rate_lo, rate_hi = residual_slope_ci(yc.index.to_numpy(), yc.to_numpy(), n_boot=args.n_boot)
        results.append({"name": ind, "span": span, "accel": accel, "gaps": gaps, "disp": disp,
                          "n": len(years), "count_trend": {"slope_per_year": rate_slope, "ci_lo": rate_lo, "ci_hi": rate_hi, "interpretation": "listed events per observed calendar year; block residual CI"}})
        c_str = f"{accel['c']:+.4f} [{accel['ci_lo']:+.4f}, {accel['ci_hi']:+.4f}]"
        g_str = (f"{gaps['slope']:+.4f} [{gaps['ci_lo']:+.4f}, {gaps['ci_hi']:+.4f}]"
                  if not np.isnan(gaps['slope']) else "n/a")
        d_str = (f"{disp['d']:.2f} [{disp['ci_lo']:.2f}, {disp['ci_hi']:.2f}]"
                  if not np.isnan(disp['d']) else "n/a")
        print(f"{ind:<35} {len(years):>4} {c_str:>32} {g_str:>30} {d_str:>22}")

    print("\nExploratory diagnostics (pointwise intervals; no fulfillment inference):")
    print("-" * 100)
    for r in results:
        acc_sig = (not np.isnan(r['accel']['ci_lo'])) and (r['accel']['ci_lo'] > 0)
        gap_sig = (not np.isnan(r['gaps']['ci_lo'])) and (r['gaps']['ci_hi'] < 0)
        disp_sig = (not np.isnan(r['disp']['ci_lo'])) and (r['disp']['ci_lo'] > 1)
        verdict = []
        if acc_sig: verdict.append("ACCELERATING")
        if gap_sig: verdict.append("SHRINKING EVENT GAPS" if r["gaps"]["resolution"] == "timestamp" else "SHRINKING OCCUPIED-YEAR GAPS")
        if disp_sig: verdict.append("CLUSTERED")
        if not verdict: verdict = ["—"]
        print(f"  {r['name']:<35} ({r['n']} events): {', '.join(verdict)}")

    # ---- Summary figure ----
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.5))
    names = [r["name"] for r in results]
    y_pos = np.arange(len(results))

    def safe_err(pts, lo, hi):
        # Clip to non-negative because matplotlib refuses negative xerr.
        # If point is outside CI (rare with bootstrap), show zero error on that side.
        def _v(x): return 0.0 if (x is None or np.isnan(x)) else float(x)
        lower = [max(0.0, _v(p) - _v(l)) for p, l in zip(pts, lo)]
        upper = [max(0.0, _v(h) - _v(p)) for p, h in zip(pts, hi)]
        return [lower, upper]

    # Panel 1: acceleration coefficient
    ax = axes[0]
    accel_pts = [r["accel"]["c"] for r in results]
    accel_lo = [r["accel"]["ci_lo"] for r in results]
    accel_hi = [r["accel"]["ci_hi"] for r in results]
    colors = ["#cc4422" if (not np.isnan(lo) and lo > 0)
                else ("#22aa44" if (not np.isnan(hi) and hi < 0) else "#888888")
                for lo, hi in zip(accel_lo, accel_hi)]
    ax.barh(y_pos, accel_pts, xerr=safe_err(accel_pts, accel_lo, accel_hi),
              color=colors, edgecolor="black", alpha=0.85, capsize=3)
    ax.axvline(0, color="black", linewidth=1)
    ax.set_yticks(y_pos); ax.set_yticklabels(names, fontsize=8.5)
    ax.set_xlabel("Curvature coefficient c (events/yr²)")
    ax.set_title("Acceleration\n(positive = cumulative curve bends upward)")
    ax.grid(axis="x", alpha=0.3)

    # Panel 2: gap slope (negative = shrinking)
    ax = axes[1]
    gap_pts = [r["gaps"]["slope"] for r in results]
    gap_lo = [r["gaps"]["ci_lo"] for r in results]
    gap_hi = [r["gaps"]["ci_hi"] for r in results]
    colors_g = ["#cc4422" if (not np.isnan(hi) and hi < 0)
                  else ("#22aa44" if (not np.isnan(lo) and lo > 0) else "#888888")
                  for lo, hi in zip(gap_lo, gap_hi)]
    ax.barh(y_pos, gap_pts, xerr=safe_err(gap_pts, gap_lo, gap_hi),
              color=colors_g, edgecolor="black", alpha=0.85, capsize=3)
    ax.axvline(0, color="black", linewidth=1)
    ax.set_yticks(y_pos); ax.set_yticklabels([""] * len(names))
    ax.set_xlabel("Gap slope (years/index; annual catalogs = occupied-year gaps)")
    ax.set_title("Shrinking gaps\n(red bars = gaps trending shorter)")
    ax.grid(axis="x", alpha=0.3)

    # Panel 3: dispersion index
    ax = axes[2]
    d_pts = [r["disp"]["d"] for r in results]
    d_lo = [r["disp"]["ci_lo"] for r in results]
    d_hi = [r["disp"]["ci_hi"] for r in results]
    colors_d = ["#cc4422" if (not np.isnan(lo) and lo > 1)
                  else ("#22aa44" if (not np.isnan(hi) and hi < 1) else "#888888")
                  for lo, hi in zip(d_lo, d_hi)]
    ax.barh(y_pos, d_pts, xerr=safe_err(d_pts, d_lo, d_hi),
              color=colors_d, edgecolor="black", alpha=0.85, capsize=3)
    ax.axvline(1, color="black", linewidth=1.0, linestyle="--", label="Poisson = 1")
    ax.set_yticks(y_pos); ax.set_yticklabels([""] * len(names))
    ax.set_xlabel("Dispersion index (variance / mean)")
    ax.set_title("Clustering\n(>1 = events bunch in time; <1 = regular)")
    ax.grid(axis="x", alpha=0.3)
    ax.legend(loc="lower right", fontsize=8)

    plt.suptitle("Exploratory event-pattern diagnostics: acceleration, gaps, clustering\n"
                  "Pointwise intervals, no multiple-test correction; quake sequences include aftershocks",
                  fontsize=12)
    plt.tight_layout()
    plt.savefig(out / "20_pattern_birthpains.png", dpi=120)
    plt.close()
    (out / "20_pattern_results.json").write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out/'20_pattern_birthpains.png'}")


if __name__ == "__main__":
    main()
