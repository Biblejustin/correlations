"""
Birth-pains pattern detection.

Trends just measure "is the line going up?" But labor pains have a more specific
signature: they accelerate, they cluster, and the gaps between contractions
shrink as labor progresses. This script tests each indicator for those three
specific patterns.

Tests per indicator (using only ≥significant-threshold events for each category):

  1. ACCELERATION — fit cumulative_count(t) = a + b·t + c·t². Test c > 0.
     Positive c means the cumulative curve bends upward — events arriving
     faster over time.

  2. SHRINKING GAPS — regress the i-th inter-event gap on i. Negative slope
     means each gap is shorter than the last, which is the textbook
     birth-pain pattern.

  3. CLUSTERING (DISPERSION INDEX) — variance/mean of yearly counts. >1 =
     overdispersed (events come in bursts), =1 = Poisson (random), <1 =
     regular spacing. Bootstrap 95% CI.

Writes figures/20_pattern_birthpains.png with a paired-bar summary of the
acceleration coefficient and the gap-trend slope across all indicators.
"""
import argparse
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


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


def fit_gap_trend(event_years, n_boot=2000, seed=42):
    """Regress inter-event gap on event index. Negative = shrinking gaps."""
    rng = np.random.default_rng(seed)
    yrs = np.sort(np.unique(np.asarray(event_years, dtype=float)))
    if len(yrs) < 3:
        return dict(slope=np.nan, ci_lo=np.nan, ci_hi=np.nan, n=len(yrs))
    gaps = np.diff(yrs)
    idx = np.arange(len(gaps))
    slope_pt, intercept = np.polyfit(idx, gaps, 1)
    boots = []
    for _ in range(n_boot):
        sample = rng.integers(0, len(gaps), len(gaps))
        s, _ = np.polyfit(idx, gaps[sample], 1)
        boots.append(s)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return dict(slope=float(slope_pt), ci_lo=float(lo), ci_hi=float(hi),
                n_gaps=len(gaps), mean_gap=float(gaps.mean()))


def dispersion_index(yearly_counts, n_boot=2000, seed=42):
    """Variance-to-mean ratio of a yearly count series. >1 = clustered."""
    rng = np.random.default_rng(seed)
    y = np.asarray(yearly_counts, dtype=float)
    if y.mean() == 0 or len(y) < 5:
        return dict(d=np.nan, ci_lo=np.nan, ci_hi=np.nan, n=len(y))
    d_pt = y.var() / y.mean() if y.mean() else np.nan
    boots = []
    for _ in range(n_boot):
        sample = y[rng.integers(0, len(y), len(y))]
        if sample.mean() > 0:
            boots.append(sample.var() / sample.mean())
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return dict(d=float(d_pt), ci_lo=float(lo), ci_hi=float(hi), n=len(y))


# ---------- Indicator loaders (returns event_year list and yearly-count series) ----------

def load_indicator(name, args):
    """Returns (event_years, yearly_counts_series, year_range_label)."""
    if name == "M>=7 quakes":
        con = sqlite3.connect(args.eq_db_1900)
        q = pd.read_sql("SELECT time_ms FROM quakes WHERE mag>=7", con)
        q["year"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.year
        q = q[q["year"].between(1900, 2025)]
        years = q["year"].tolist()
        yc = q.groupby("year").size().reindex(range(1900, 2026), fill_value=0)
        return years, yc, "1900-2025"
    if name == "M>=8 quakes":
        con = sqlite3.connect(args.eq_db_1900)
        q = pd.read_sql("SELECT time_ms FROM quakes WHERE mag>=8", con)
        q["year"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.year
        q = q[q["year"].between(1900, 2025)]
        years = q["year"].tolist()
        yc = q.groupby("year").size().reindex(range(1900, 2026), fill_value=0)
        return years, yc, "1900-2025"
    if name == "VEI>=6 eruptions":
        df = pd.read_csv(args.volcanoes_csv)
        df["vei"] = df["vei"].astype(str).str.extract(r"(\d+)")[0].astype(float)
        df = df[(df["vei"] >= 6) & (df["year"] >= 1500) & (df["year"] <= 2025)]
        years = df["year"].tolist()
        yc = df.groupby("year").size().reindex(range(1500, 2026), fill_value=0)
        return years, yc, "1500-2025"
    if name == "X1+ flares":
        df = pd.read_csv(args.flares_csv, parse_dates=["date"])
        df["year"] = df["date"].dt.year
        df = df[df["year"].between(1976, 2025)]
        years = df["year"].tolist()
        yc = df.groupby("year").size().reindex(range(1976, 2026), fill_value=0)
        return years, yc, "1976-2025"
    if name == "Big wars (>=1M deaths)":
        df = pd.read_csv(args.wars_csv)
        df = df[(df["deaths_estimate"] >= 1_000_000) & (df["start_year"] >= 1500) & (df["start_year"] <= 2025)]
        years = df["start_year"].tolist()
        yc = df.groupby("start_year").size().reindex(range(1500, 2026), fill_value=0)
        return years, yc, "1500-2025"
    if name == "Great famines (>=1M deaths)":
        df = pd.read_csv(args.famines_wpf_orig)  # famines_wpf.csv has per-event totals
        df = df[df["wpf_authoritative_mortality_estimate"] >= 1_000_000]
        df = df[(df["year"] >= 1870) & (df["year"] <= 2025)]
        years = df["year"].tolist()
        yc = df.groupby("year").size().reindex(range(1870, 2026), fill_value=0)
        return years, yc, "1870-2025"
    if name == "Great pandemics (>=1M deaths)":
        df = pd.read_csv(args.pandemics_csv)
        df = df[df["deaths_estimate"] >= 1_000_000]
        df = df[(df["start_year"] >= 1500) & (df["start_year"] <= 2025)]
        years = df["start_year"].tolist()
        yc = df.groupby("start_year").size().reindex(range(1500, 2026), fill_value=0)
        return years, yc, "1500-2025"
    if name == "Great cyclones (>=10k deaths)":
        df = pd.read_csv(args.cyclones_csv)
        df = df[df["deaths_estimate"] >= 10_000]
        df = df[(df["year"] >= 1700) & (df["year"] <= 2025)]
        years = df["year"].tolist()
        yc = df.groupby("year").size().reindex(range(1700, 2026), fill_value=0)
        return years, yc, "1700-2025"
    if name == "Major floods (>=1000 deaths)":
        df = pd.read_csv(args.floods_csv, low_memory=False)
        df["deaths"] = pd.to_numeric(df["deaths"], errors="coerce").fillna(0)
        df = df[df["deaths"] >= 1000]
        df["year"] = pd.to_datetime(df["start_date"], errors="coerce").dt.year
        df = df.dropna(subset=["year"])
        if "match_group_id" in df.columns:
            with_g = df[df["match_group_id"].notna()].drop_duplicates(subset=["match_group_id"])
            without_g = df[df["match_group_id"].isna()]
            df = pd.concat([with_g, without_g], ignore_index=True)
        df = df[df["year"].between(1900, 2025)]
        years = df["year"].astype(int).tolist()
        yc = df.groupby(df["year"].astype(int)).size().reindex(range(1900, 2026), fill_value=0)
        return years, yc, "1900-2025"
    if name == "Major droughts (>=1M affected)":
        df = pd.read_csv(args.droughts_csv)
        df["start_year"] = pd.to_numeric(df["start_year"], errors="coerce")
        df["deaths_estimate"] = pd.to_numeric(df["deaths_estimate"], errors="coerce").fillna(0)
        df["people_affected"] = pd.to_numeric(df["people_affected"], errors="coerce").fillna(0)
        df["intensity"] = df[["deaths_estimate", "people_affected"]].max(axis=1)
        df = df[(df["intensity"] >= 1_000_000) & df["start_year"].between(1850, 2025)]
        years = df["start_year"].astype(int).tolist()
        yc = df.groupby(df["start_year"].astype(int)).size().reindex(range(1850, 2026), fill_value=0)
        return years, yc, "1850-2025"
    if name == "Major refugee crises (>=1M)":
        df = pd.read_csv(args.refugees_csv)
        df["start_year"] = pd.to_numeric(df["start_year"], errors="coerce")
        df["displaced_estimate"] = pd.to_numeric(df["displaced_estimate"], errors="coerce").fillna(0)
        df = df[(df["displaced_estimate"] >= 1_000_000) & df["start_year"].between(1947, 2025)]
        years = df["start_year"].astype(int).tolist()
        yc = df.groupby(df["start_year"].astype(int)).size().reindex(range(1947, 2026), fill_value=0)
        return years, yc, "1947-2025"
    if name == "Severe economic crises":
        df = pd.read_csv(args.economic_csv)
        order = {"medium": 0, "severe": 1, "extreme": 2}
        df["sev_rank"] = df["severity"].map(order).fillna(-1)
        df = df[(df["sev_rank"] >= 1) & df["year"].between(1800, 2025)]
        years = df["year"].astype(int).tolist()
        yc = df.groupby(df["year"].astype(int)).size().reindex(range(1800, 2026), fill_value=0)
        return years, yc, "1800-2025"
    if name == "Successful coups":
        df = pd.read_csv(args.coups_csv)
        df = df[(df["outcome"] == "successful") & df["year"].between(1950, 2025)]
        years = df["year"].astype(int).tolist()
        yc = df.groupby(df["year"].astype(int)).size().reindex(range(1950, 2026), fill_value=0)
        return years, yc, "1950-2025"
    raise ValueError(name)


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
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    indicators = [
        "M>=7 quakes", "M>=8 quakes", "VEI>=6 eruptions", "X1+ flares",
        "Big wars (>=1M deaths)", "Great famines (>=1M deaths)",
        "Great pandemics (>=1M deaths)", "Great cyclones (>=10k deaths)",
        "Major floods (>=1000 deaths)", "Major droughts (>=1M affected)",
        "Major refugee crises (>=1M)", "Severe economic crises",
        "Successful coups",
    ]

    results = []
    print(f"{'Indicator':<35} {'n':>4} {'curvature c (CI)':>32} {'gap slope (CI)':>30} {'dispersion (CI)':>22}")
    print("-" * 130)
    for ind in indicators:
        years, yc, span = load_indicator(ind, args)
        accel = fit_quadratic_acceleration(years)
        gaps = fit_gap_trend(years)
        disp = dispersion_index(yc.values)
        results.append({"name": ind, "span": span, "accel": accel, "gaps": gaps, "disp": disp,
                          "n": len(years)})
        c_str = f"{accel['c']:+.4f} [{accel['ci_lo']:+.4f}, {accel['ci_hi']:+.4f}]"
        g_str = (f"{gaps['slope']:+.4f} [{gaps['ci_lo']:+.4f}, {gaps['ci_hi']:+.4f}]"
                  if not np.isnan(gaps['slope']) else "n/a")
        d_str = (f"{disp['d']:.2f} [{disp['ci_lo']:.2f}, {disp['ci_hi']:.2f}]"
                  if not np.isnan(disp['d']) else "n/a")
        print(f"{ind:<35} {len(years):>4} {c_str:>32} {g_str:>30} {d_str:>22}")

    print("\nVerdicts (acceleration AND shrinking gaps would be the strongest birth-pains pattern):")
    print("-" * 100)
    for r in results:
        acc_sig = (not np.isnan(r['accel']['ci_lo'])) and (r['accel']['ci_lo'] > 0)
        gap_sig = (not np.isnan(r['gaps']['ci_lo'])) and (r['gaps']['ci_hi'] < 0)
        disp_sig = (not np.isnan(r['disp']['ci_lo'])) and (r['disp']['ci_lo'] > 1)
        verdict = []
        if acc_sig: verdict.append("ACCELERATING")
        if gap_sig: verdict.append("SHRINKING GAPS")
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
    ax.set_xlabel("Inter-event gap slope (years per event index)")
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

    plt.suptitle("Birth-pains pattern test: acceleration, shrinking gaps, clustering\n"
                  "Red = pattern detected (95% CI); Grey = not detected; Green = opposite of pattern",
                  fontsize=12)
    plt.tight_layout()
    plt.savefig(out / "20_pattern_birthpains.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'20_pattern_birthpains.png'}")


if __name__ == "__main__":
    main()
