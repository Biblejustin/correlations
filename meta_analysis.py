"""
Methodological deepening across the full test grid.

Sections:
  1. Bootstrap CIs on the marginal residuals (flood ±0d 2.15×, flares ±0d 1.51×)
  2. Drop-1 leverage analysis (does any single event drive the result?)
  3. Full N×N cross-correlation matrix on regime-detrended yearly series
  4. FDR (Benjamini-Hochberg) replacement for Bonferroni
"""
import argparse
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from correlate_events import (
    load_yearly_quakes_m7,
    load_yearly_flares_x1,
    load_yearly_wars,
    load_yearly_war_deaths_active,
    load_yearly_famine_deaths_wpf,
    load_yearly_flood_events,
    load_yearly_flood_deaths,
    load_flood_event_dates,
    load_yearly_pandemic_deaths,
    load_yearly_volcanoes,
    load_yearly_cyclones,
    load_yearly_cyclone_deaths,
    load_yearly_terrorism_deaths,
    load_yearly_stock_drawdown_intensity,
)
from detection_regimes import REGIMES, piecewise_detrend


# ============================================================
# 1. BOOTSTRAP CI ON MARGINAL RESIDUALS
# ============================================================

def bootstrap_window_ratio(event_dates, target_dates, all_dates, window_days,
                             n_boot=10000, rng=None):
    """Bootstrap CI on the observed/expected ratio for a window test.

    Resamples target_dates (the larger set, usually M>=7 quakes) with
    replacement; recomputes the ratio each iteration.
    """
    rng = rng or np.random.default_rng(42)
    target = np.array(sorted(target_dates))
    n_target = len(target)
    n_total = len(all_dates)

    # Build window once (it doesn't change)
    win = set()
    for d in event_dates:
        for k in range(-window_days, window_days + 1):
            win.add(d + pd.Timedelta(days=k))
    win &= all_dates
    p_chance = len(win) / n_total

    ratios = np.empty(n_boot)
    for i in range(n_boot):
        sample_idx = rng.integers(0, n_target, n_target)
        sample = target[sample_idx]
        observed = sum(1 for d in sample if d in win)
        expected = n_target * p_chance
        ratios[i] = observed / expected if expected else np.nan
    return {
        "point_estimate": (sum(1 for d in target if d in win)) / (n_target * p_chance) if p_chance else float("nan"),
        "ci_2_5": float(np.percentile(ratios, 2.5)),
        "ci_97_5": float(np.percentile(ratios, 97.5)),
        "median": float(np.median(ratios)),
        "n_boot": n_boot,
    }


def run_bootstrap_section(args):
    print("=" * 80)
    print("1. BOOTSTRAP CIs ON MARGINAL RESIDUAL SIGNALS")
    print("=" * 80)

    # Flood ±0d test (tsunami-excluded)
    flood_dates = load_flood_event_dates(args.floods_csv, deaths_min=1000,
                                          exclude_tsunami=True)
    flood_dates = [d for d in flood_dates if 1965 <= d.year <= 2025]
    con = sqlite3.connect(args.eq_db_modern)
    q = pd.read_sql("SELECT time_ms, mag FROM quakes WHERE mag>=7", con)
    q["date"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    q = q[q["date"].dt.year.between(1965, 2025)]
    m7_dates = q["date"].tolist()
    all_dates = set(pd.date_range("1965-01-01", "2025-12-31", freq="D"))

    print(f"\nFlood (>=1000 deaths, tsunami-excluded) × M>=7 quakes, ±0 day window:")
    for w in (0, 1):
        r = bootstrap_window_ratio(flood_dates, m7_dates, all_dates, window_days=w, n_boot=10000)
        print(f"  ±{w}d: point={r['point_estimate']:.3f}x  "
              f"95% CI [{r['ci_2_5']:.3f}, {r['ci_97_5']:.3f}]  (10k bootstrap)")

    # Flares ±0d test
    fl = pd.read_csv(args.flares_csv, parse_dates=["date"])
    fl = fl[fl["date"].dt.year.between(1976, 2025)]
    flare_dates = list(fl["date"].dt.normalize())
    q2 = q[q["date"].dt.year.between(1976, 2025)]
    m7_dates_flare = q2["date"].tolist()
    all_dates_flare = set(pd.date_range("1976-01-01", "2025-12-31", freq="D"))

    print(f"\nX1+ flares × M>=7 quakes, ±0 day window:")
    for w in (0, 1):
        r = bootstrap_window_ratio(flare_dates, m7_dates_flare, all_dates_flare,
                                     window_days=w, n_boot=10000)
        print(f"  ±{w}d: point={r['point_estimate']:.3f}x  "
              f"95% CI [{r['ci_2_5']:.3f}, {r['ci_97_5']:.3f}]")

    print("\nInterpretation: any 95% CI containing 1.0 is consistent with chance.")


# ============================================================
# 2. DROP-1 LEVERAGE
# ============================================================

def drop1_leverage(series_a, series_b, regime_a, regime_b, label, top_n=5):
    """For each year in the overlap, recompute detrended r after dropping it.
    Returns the years with largest |r_dropped - r_full|."""
    overlap = series_a.index.intersection(series_b.index)
    a = series_a.loc[overlap].astype(float)
    b = series_b.loc[overlap].astype(float)
    a_d = piecewise_detrend(a, REGIMES.get(regime_a, []))
    b_d = piecewise_detrend(b, REGIMES.get(regime_b, []))
    mask = ~(a_d.isna() | b_d.isna())
    a_d = a_d[mask]; b_d = b_d[mask]
    if len(a_d) < 10:
        return None

    r_full, _ = stats.pearsonr(a_d, b_d)
    leverages = []
    for yr in a_d.index:
        a2 = a_d.drop(yr); b2 = b_d.drop(yr)
        r_drop, _ = stats.pearsonr(a2, b2)
        leverages.append((int(yr), float(r_drop), float(r_drop - r_full)))
    leverages.sort(key=lambda x: abs(x[2]), reverse=True)
    print(f"\n{label} (full detrended r = {r_full:+.3f}):")
    print("  Top single-year leverages:")
    for yr, r_drop, delta in leverages[:top_n]:
        print(f"    drop {yr}: r becomes {r_drop:+.3f}  (Δ = {delta:+.3f})")
    return {"r_full": r_full, "leverages": leverages}


def run_leverage_section(args):
    print("\n" + "=" * 80)
    print("2. DROP-1 LEVERAGE ANALYSIS (which years drive each result?)")
    print("=" * 80)

    m7 = load_yearly_quakes_m7(args.eq_db_1900, 1900, 2025)
    xf = load_yearly_flares_x1(args.flares_csv, 1976, 2025)
    wars = load_yearly_wars(args.wars_csv, 1976, 2025)
    wars_d = load_yearly_war_deaths_active(args.wars_csv, 1976, 2025, log10_transform=True)

    drop1_leverage(wars, xf, "wars_global", "flares_x",
                    "Wars onset count × X1+ flares (the +0.27 result)")
    drop1_leverage(wars_d, xf, "wars_global", "flares_x",
                    "War deaths (log10) × X1+ flares (the +0.014 result)")
    drop1_leverage(m7, xf, "quakes_m7", "flares_x",
                    "M>=7 quakes × X1+ flares (1976-2025)")


# ============================================================
# 3. CROSS-CORRELATION MATRIX
# ============================================================

def run_cross_corr_matrix(args, out):
    print("\n" + "=" * 80)
    print("3. CROSS-CORRELATION MATRIX (regime-detrended, 1900-2025)")
    print("=" * 80)

    series_dict = {
        "M>=7 quakes": (load_yearly_quakes_m7(args.eq_db_1900, 1900, 2025), "quakes_m7"),
        "War deaths log10": (load_yearly_war_deaths_active(args.wars_csv, 1900, 2025, log10_transform=True), "wars_global"),
        "Famine deaths log10 (WPF)": (load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, 2025, log10_transform=True), "famines"),
        "Flood deaths log10": (load_yearly_flood_deaths(args.floods_csv, 1900, 2025, log10_transform=True), "floods"),
        "Pandemic deaths log10": (load_yearly_pandemic_deaths(args.pandemics_csv, 1900, 2025, log10_transform=True), "pandemics"),
        "Volcanoes VEI>=5": (load_yearly_volcanoes(args.volcanoes_csv, 1900, 2025, vei_min=5), "volcanoes"),
        "Cyclone deaths log10": (load_yearly_cyclone_deaths(args.cyclones_csv, 1900, 2025, log10_transform=True), "cyclones"),
    }
    # Add flares only over its valid range
    xf_only = load_yearly_flares_x1(args.flares_csv, 1976, 2025)
    # Pad with NaN to 1900-2025 for matrix alignment
    xf_padded = pd.Series(np.nan, index=range(1900, 2026))
    xf_padded.loc[xf_only.index] = xf_only.values
    xf_padded.name = "xflare_count"
    series_dict["X1+ flares"] = (xf_padded, "flares_x")

    # Terrorism: GTD via OWID, 1970-2021. Pad with NaN for 1900-2025 matrix alignment.
    terror_only = load_yearly_terrorism_deaths(args.terrorism_csv, 1970, 2021, log10_transform=True)
    terror_padded = pd.Series(np.nan, index=range(1900, 2026))
    terror_padded.loc[terror_only.index] = terror_only.values
    terror_padded.name = "terrorism"
    series_dict["Terrorism deaths log10"] = (terror_padded, "terrorism")

    # Stock crashes (S&P 500 / pre-1957 equivalents): peak-to-trough drawdown sum per year
    crashes_d = load_yearly_stock_drawdown_intensity(args.crashes_csv, 1900, 2025, log10_transform=True)
    series_dict["Stock crash intensity log10"] = (crashes_d, "stock_crashes")

    names = list(series_dict.keys())
    n = len(names)
    R = np.full((n, n), np.nan)
    P = np.full((n, n), np.nan)
    for i, ni in enumerate(names):
        si, ki = series_dict[ni]
        si_d = piecewise_detrend(si.astype(float), REGIMES.get(ki, []))
        for j, nj in enumerate(names):
            sj, kj = series_dict[nj]
            sj_d = piecewise_detrend(sj.astype(float), REGIMES.get(kj, []))
            mask = ~(si_d.isna() | sj_d.isna())
            if mask.sum() < 5:
                continue
            r, p = stats.pearsonr(si_d[mask], sj_d[mask])
            R[i, j] = r
            P[i, j] = p

    print("\nPearson r (regime-detrended):")
    df_r = pd.DataFrame(R, index=names, columns=names).round(3)
    print(df_r.to_string())
    print("\nP-values:")
    df_p = pd.DataFrame(P, index=names, columns=names).round(3)
    print(df_p.to_string())

    # Heatmap figure
    fig, ax = plt.subplots(figsize=(11, 9))
    im = ax.imshow(R, cmap="RdBu_r", vmin=-0.5, vmax=0.5, aspect="auto")
    ax.set_xticks(range(n)); ax.set_yticks(range(n))
    ax.set_xticklabels(names, rotation=45, ha="right")
    ax.set_yticklabels(names)
    for i in range(n):
        for j in range(n):
            if not np.isnan(R[i, j]):
                color = "black" if abs(R[i, j]) < 0.3 else "white"
                ax.text(j, i, f"{R[i, j]:+.2f}",
                        ha="center", va="center", color=color, fontsize=8)
    plt.colorbar(im, label="Pearson r (regime-detrended)")
    plt.title("Cross-correlation matrix — all regime-detrended yearly series, 1900-2025\n"
              "Off-diagonal cells: pairwise correlation; all near 0")
    plt.tight_layout()
    plt.savefig(out / "18_cross_correlation_matrix.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'18_cross_correlation_matrix.png'}")

    # Return flattened off-diagonal p-values for FDR
    pvals_flat = []
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            if not np.isnan(P[i, j]):
                pvals_flat.append(P[i, j])
                pairs.append((names[i], names[j], R[i, j]))
    return pvals_flat, pairs


# ============================================================
# 4. FDR (BENJAMINI-HOCHBERG)
# ============================================================

def benjamini_hochberg(pvalues, alpha=0.05):
    """Return (rejected, p_adj) per BH procedure."""
    p = np.array(pvalues, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    crit = (np.arange(1, n + 1) / n) * alpha
    # Find largest k where ranked[k] <= crit[k]
    below = ranked <= crit
    if not below.any():
        cutoff = -1
    else:
        cutoff = np.max(np.where(below)[0])
    rejected = np.zeros(n, dtype=bool)
    rejected[order[: cutoff + 1]] = True
    # Adjusted p-values (BH-style)
    p_adj_ranked = ranked * n / np.arange(1, n + 1)
    # ensure monotone non-increasing from right
    p_adj_ranked = np.minimum.accumulate(p_adj_ranked[::-1])[::-1]
    p_adj_ranked = np.minimum(p_adj_ranked, 1.0)
    p_adj = np.empty(n)
    p_adj[order] = p_adj_ranked
    return rejected, p_adj


def run_fdr_section(pvals, pairs):
    print("\n" + "=" * 80)
    print("4. FDR (Benjamini-Hochberg) — less conservative than Bonferroni")
    print("=" * 80)

    if not pvals:
        print("  No off-diagonal p-values to correct.")
        return

    rejected, p_adj = benjamini_hochberg(pvals, alpha=0.05)
    print(f"\nFDR-corrected pairwise tests (α = 0.05, n_tests = {len(pvals)}):")
    print(f"  Rejected null (FDR-significant): {rejected.sum()} of {len(pvals)}")
    print()
    print(f"  {'pair':<55} {'r':>8} {'raw p':>10} {'BH p_adj':>10} {'sig?':>6}")
    print("  " + "-" * 95)
    # Sort by raw p ascending
    order = np.argsort(pvals)
    for idx in order:
        a, b, r = pairs[idx]
        sig = "**" if rejected[idx] else "ns"
        print(f"  {a + ' × ' + b:<55} {r:+8.3f} {pvals[idx]:10.4f} {p_adj[idx]:10.4f} {sig:>6}")

    # Headline tests for Bonferroni comparison
    print(f"\nFor comparison, Bonferroni cutoff at α=0.05 for {len(pvals)} tests: "
          f"raw p < {0.05/len(pvals):.4g}")
    print(f"Number passing Bonferroni: {sum(1 for p in pvals if p < 0.05/len(pvals))}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eq-db-1900", default="../earthquakes/quakes_1900.sqlite")
    ap.add_argument("--eq-db-modern", default="../earthquakes/quakes.sqlite")
    ap.add_argument("--flares-csv", default="data/flares_xclass.csv")
    ap.add_argument("--wars-csv", default="data/wars.csv")
    ap.add_argument("--floods-csv", default="data/floods.csv")
    ap.add_argument("--famines-wpf-csv", default="data/famine_deaths_by_year.csv")
    ap.add_argument("--pandemics-csv", default="data/pandemics.csv")
    ap.add_argument("--volcanoes-csv", default="data/volcanoes.csv")
    ap.add_argument("--cyclones-csv", default="data/cyclones.csv")
    ap.add_argument("--terrorism-csv", default="data/terrorism.csv")
    ap.add_argument("--crashes-csv", default="data/stock_crashes.csv")
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    run_bootstrap_section(args)
    run_leverage_section(args)
    pvals, pairs = run_cross_corr_matrix(args, out)
    run_fdr_section(pvals, pairs)


if __name__ == "__main__":
    main()
