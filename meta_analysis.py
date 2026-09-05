"""
Coverage-aware exploratory annual matrix and event-window diagnostics.

The ten-indicator matrix uses a full45-pair BH family and a conservative
3/5/10-year block-null sensitivity. Annual overlap is finite and contiguous.
Daily-window ratio intervals preserve shared annual blocks and are descriptive,
not chance tests. Source release coverage never comes from last qualifying event.
"""
import argparse
import json
from contextlib import closing
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from statistical_helpers import (last_complete_year, contiguous_overlap, bh_adjust,
                                 block_indices)
END_YEAR = last_complete_year()

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
                           n_boot=20000, rng=None):
    """Descriptive ratio interval from shared three-calendar-year blocks.

    Every year's exposure, event windows, quake counts, and observed hits move
    together. This retains within-year timing/clustering; it is an uncertainty
    interval conditional on selected catalogues, not a random-coincidence null.
    """
    rng = rng or np.random.default_rng(42)
    exposure = set(pd.Timestamp(d).normalize() for d in all_dates)
    target = [pd.Timestamp(d).normalize() for d in target_dates if pd.Timestamp(d).normalize() in exposure]
    window = {pd.Timestamp(d).normalize() + pd.Timedelta(days=k)
              for d in event_dates for k in range(-window_days, window_days + 1)} & exposure
    empty = dict(point_estimate=np.nan, ci_2_5=np.nan, ci_97_5=np.nan,
                 median=np.nan, n_boot=n_boot, status="unavailable: empty events, targets, or exposure")
    if not exposure or not target or not window:
        return empty
    years = sorted(set(d.year for d in exposure))
    if len(years) < 6 or np.any(np.diff(years) != 1):
        return {**empty, "status": "unavailable: need six contiguous exposed calendar years"}
    annual = pd.DataFrame(0.0, index=years, columns=["exposure", "window", "target", "hits"])
    for day in exposure:
        annual.loc[day.year, "exposure"] += 1
    for day in window:
        annual.loc[day.year, "window"] += 1
    for day in target:
        annual.loc[day.year, "target"] += 1
        annual.loc[day.year, "hits"] += int(day in window)
    def ratio(totals):
        expected = totals[2] * totals[1] / totals[0]
        return totals[3] / expected if expected > 0 else np.nan
    point = ratio(annual.to_numpy().sum(axis=0))
    values = annual.to_numpy()
    ratios = np.asarray([ratio(values[block_indices(len(years), rng, 3)].sum(axis=0)) for _ in range(n_boot)])
    ratios = ratios[np.isfinite(ratios)]
    lo, median, hi = np.percentile(ratios, [2.5, 50, 97.5]) if len(ratios) else (np.nan, np.nan, np.nan)
    return dict(point_estimate=float(point), ci_2_5=float(lo), ci_97_5=float(hi), median=float(median),
                n_boot=n_boot, finite_resamples=len(ratios), n_years=len(years),
                start_year=min(years), end_year=max(years), n_targets=len(target),
                status="descriptive shared-year-block interval; not a chance test")


def run_bootstrap_section(args):
    print("1. DAILY-WINDOW RATIOS: DESCRIPTIVE SHARED-YEAR-BLOCK INTERVALS")
    end = getattr(args, "year_hi", END_YEAR)
    n_boot = getattr(args, "n_boot", 20000)
    with closing(sqlite3.connect(f"file:{Path(args.eq_db_modern).resolve()}?mode=ro", uri=True)) as con:
        q = pd.read_sql("SELECT time_ms FROM quakes WHERE mag>=7", con)
    q["date"] = pd.to_datetime(q.time_ms, unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    quake_scope = load_yearly_quakes_m7(args.eq_db_modern, 1965, end)
    flood_scope = load_yearly_flood_events(args.floods_csv, 1965, end)
    flare_scope = load_yearly_flares_x1(args.flares_csv, 1976, end)
    floods = load_flood_event_dates(args.floods_csv, deaths_min=1000, exclude_tsunami=True)
    flares = pd.read_csv(args.flares_csv, parse_dates=["date"])
    flare_magnitude = pd.to_numeric(flares["class"].astype(str).str.extract(r"^X([0-9.]+)")[0], errors="coerce")
    flares = list(flares.loc[flare_magnitude >= 1, "date"].dt.normalize())
    rows = []
    for label, events, scope in [("Flood >=1000 deaths, tsunami excluded", floods, flood_scope),
                                  ("X1+ flares", flares, flare_scope)]:
        try:
            observed = contiguous_overlap({"quakes": quake_scope, "source": scope})
        except ValueError as exc:
            print(f"{label}: unavailable: {exc}")
            continue
        start, finish = int(observed.index.min()), int(observed.index.max())
        exposed = set(pd.date_range(f"{start}-01-01", f"{finish}-12-31"))
        for width in (0, 1):
            result = bootstrap_window_ratio(events, q.date.tolist(), exposed, width, n_boot=n_boot)
            rows.append({"source": label, "window_days": width, **result})
            print(f"{label} ±{width}d: {result['point_estimate']:.3f}x "
                  f"[{result['ci_2_5']:.3f}, {result['ci_97_5']:.3f}]; {result['status']}")
    pd.DataFrame(rows).to_csv(Path(args.out) / "18_window_ratio_diagnostics.csv", index=False)


# ============================================================
# 2. DROP-1 LEVERAGE
# ============================================================

def drop1_leverage(series_a, series_b, regime_a, regime_b, label, top_n=5):
    """Descriptive leave-one-year influence, refitting regime trends each time."""
    try:
        frame = contiguous_overlap({"a": series_a, "b": series_b}, min_years=10)
    except ValueError:
        return None
    def residual_r(data):
        a = piecewise_detrend(data.a, REGIMES.get(regime_a, []))
        b = piecewise_detrend(data.b, REGIMES.get(regime_b, []))
        return float(np.corrcoef(a, b)[0, 1]) if min(a.std(), b.std()) > 1e-12 else np.nan
    full = residual_r(frame)
    if not np.isfinite(full):
        return None
    rows = [(int(year), residual_r(frame.drop(year))) for year in frame.index]
    leverages = [(year, r, r - full) for year, r in rows if np.isfinite(r)]
    leverages.sort(key=lambda item: abs(item[2]), reverse=True)
    print(f"\n{label}: full r={full:+.3f}; detrending refitted after each deletion")
    for year, r, delta in leverages[:top_n]:
        print(f"  drop {year}: r={r:+.3f}, delta={delta:+.3f}")
    return {"r_full": full, "leverages": leverages}


def run_leverage_section(args):
    print("\n" + "=" * 80)
    print("2. DROP-1 LEVERAGE ANALYSIS (which years drive each result?)")
    print("=" * 80)

    end = getattr(args, "year_hi", END_YEAR)
    m7 = load_yearly_quakes_m7(args.eq_db_1900, 1900, end)
    xf = load_yearly_flares_x1(args.flares_csv, 1976, end)
    wars = load_yearly_wars(args.wars_csv, 1976, end)
    wars_d = load_yearly_war_deaths_active(args.wars_csv, 1976, END_YEAR, log10_transform=True)

    drop1_leverage(wars, xf, "wars_global", "flares_x",
                    "Wars onset count × X1+ flares")
    drop1_leverage(wars_d, xf, "wars_global", "flares_x",
                    "War deaths (log10) × X1+ flares")
    drop1_leverage(m7, xf, "quakes_m7", "flares_x",
                    f"M>=7 quakes × X1+ flares (1976-{end})")


# ============================================================
# 3. CROSS-CORRELATION MATRIX
# ============================================================

def independent_block_correlation_test(x, y, n_boot=20000, seed=42, block_lengths=(3, 5, 10)):
    """Two-sided independence null retaining local serial dependence.

    Independently resample each annual residual series in circular moving
    blocks. Report the largest p across predeclared block lengths, so a
    result must survive all temporal sensitivities. Approximate inference
    assumes stationary residual blocks; no causal interpretation follows.
    """
    x, y = np.asarray(x, float), np.asarray(y, float)
    if x.shape != y.shape or x.ndim != 1 or len(x) < 20 or not np.isfinite(x).all() or not np.isfinite(y).all():
        return dict(r=np.nan, p=np.nan, p_iid_diagnostic=np.nan, status="insufficient finite contiguous data")
    if min(np.std(x), np.std(y)) <= 1e-12:
        return dict(r=np.nan, p=np.nan, p_iid_diagnostic=np.nan, status="constant residual series")
    r, p_iid = stats.pearsonr(x, y)
    rng = np.random.default_rng(seed)
    p_by_block = {}
    n = len(x)
    for length in block_lengths:
        if length > n // 2:
            continue
        exceed, valid = 0, 0
        for start in range(0, n_boot, 500):
            batch = min(500, n_boot - start)
            n_blocks = int(np.ceil(n / length))
            ix = ((rng.integers(0, n, (batch, n_blocks, 1)) + np.arange(length)) % n).reshape(batch, -1)[:, :n]
            iy = ((rng.integers(0, n, (batch, n_blocks, 1)) + np.arange(length)) % n).reshape(batch, -1)[:, :n]
            bx, by = x[ix], y[iy]
            bx -= bx.mean(axis=1, keepdims=True); by -= by.mean(axis=1, keepdims=True)
            denominator = np.sqrt(np.sum(bx * bx, axis=1) * np.sum(by * by, axis=1))
            finite = denominator > 1e-12
            rb = np.divide(np.sum(bx * by, axis=1), denominator, out=np.zeros(batch), where=finite)
            exceed += int(np.sum(np.abs(rb[finite]) >= abs(r)))
            valid += int(finite.sum())
        p_by_block[f"p_block_{length}"] = (1 + exceed) / (1 + valid) if valid else np.nan
    p = max(p_by_block.values(), default=np.nan)
    return dict(r=float(r), p=float(p), p_iid_diagnostic=float(p_iid),
                **p_by_block, n_boot=n_boot, p_mc_se=float(np.sqrt(p * (1 - p) / (n_boot + 1))), status="exploratory block-null inference")


def cross_correlation_tests(series_dict, n_boot=20000):
    """Every planned pair, including unavailable tests, with BH family q-values."""
    rows = []
    names = list(series_dict)
    for i, name_a in enumerate(names):
        source_a, regime_a = series_dict[name_a]
        for name_b in names[i + 1:]:
            source_b, regime_b = series_dict[name_b]
            row = dict(a=name_a, b=name_b, n=0, start_year=np.nan, end_year=np.nan)
            try:
                frame = contiguous_overlap({"a": source_a, "b": source_b}, min_years=20)
                a = piecewise_detrend(frame.a, REGIMES.get(regime_a, []))
                b = piecewise_detrend(frame.b, REGIMES.get(regime_b, []))
                result = independent_block_correlation_test(a.to_numpy(), b.to_numpy(), n_boot=n_boot)
                row.update(n=len(frame), start_year=int(frame.index.min()), end_year=int(frame.index.max()))
            except ValueError as exc:
                result = dict(r=np.nan, p=np.nan, p_iid_diagnostic=np.nan, status=str(exc))
            rows.append({**row, **result})
    frame = pd.DataFrame(rows)
    frame["q"] = bh_adjust(frame.p)
    frame["family_size"] = len(frame)
    frame["fdr_significant"] = frame.q < .05
    return frame


def run_cross_corr_matrix(args, out):
    end = getattr(args, "year_hi", END_YEAR)
    print("\n" + "=" * 80)
    print(f"3. CROSS-CORRELATION MATRIX (regime-detrended, 1900-{end})")
    print("=" * 80)

    series_dict = {
        "M>=7 quakes": (load_yearly_quakes_m7(args.eq_db_1900, 1900, end), "quakes_m7"),
        "War deaths log10": (load_yearly_war_deaths_active(args.wars_csv, 1900, end, log10_transform=True), "wars_global"),
        "Famine deaths log10 (WPF)": (load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, end, log10_transform=True), "famines"),
        "Flood deaths log10": (load_yearly_flood_deaths(args.floods_csv, 1900, end, log10_transform=True), "floods"),
        "Pandemic deaths log10": (load_yearly_pandemic_deaths(args.pandemics_csv, 1900, end, log10_transform=True), "pandemics"),
        "Volcanoes VEI>=5": (load_yearly_volcanoes(args.volcanoes_csv, 1900, end, vei_min=5), "volcanoes"),
        "Cyclone deaths log10": (load_yearly_cyclone_deaths(args.cyclones_csv, 1900, end, log10_transform=True), "cyclones"),
    }
    series_dict["X1+ flares"] = (load_yearly_flares_x1(args.flares_csv, 1976, end), "flares_x")
    series_dict["Terrorism deaths log10"] = (load_yearly_terrorism_deaths(args.terrorism_csv, 1970, end, log10_transform=True), "terrorism")
    series_dict["Stock crash intensity log10"] = (load_yearly_stock_drawdown_intensity(args.crashes_csv, 1900, end, log10_transform=True), "stock_crashes")
    names = list(series_dict)
    print("\nCoverage comes solely from source declarations and missing-estimate masks:")
    coverage = {}
    for label, (series, _) in series_dict.items():
        observed = series.dropna()
        coverage[label] = dict(observed_years=len(observed),
                               first=int(observed.index.min()) if len(observed) else None,
                               last=int(observed.index.max()) if len(observed) else None)
        print(f"  {label}: {coverage[label]}")
    tests = cross_correlation_tests(series_dict, n_boot=getattr(args, "n_boot", 20000))
    tests.to_csv(out / "18_cross_correlation_results.csv", index=False)
    tests.to_json(out / "18_cross_correlation_results.json", orient="records", indent=2)
    metadata = dict(method="independent circular moving-block null", block_lengths=[3, 5, 10],
                    selected_p="maximum across prespecified block lengths", n_boot=getattr(args, "n_boot", 20000),
                    planned_family_size=len(tests), coverage=coverage,
                    overlap="longest contiguous finite observed annual overlap, minimum20 years; refit regime trends on overlap",
                    limitations=["approximate stationary residual-block null", "iid p is diagnostic only",
                                 "selected-event allocation proxies and historical reporting changes", "no causality or independence conclusion from nonsignificance"])
    (out / "18_cross_correlation_method.json").write_text(json.dumps(metadata, indent=2))
    n = len(names)
    R = np.full((n, n), np.nan)
    Q = np.full((n, n), np.nan)
    for i, name in enumerate(names):
        try:
            series = contiguous_overlap({"value": series_dict[name][0]}, min_years=20).value
            if series.std() > 1e-12:
                R[i, i] = 1
        except ValueError:
            pass
    for row in tests.itertuples():
        i, j = names.index(row.a), names.index(row.b)
        R[i, j] = R[j, i] = row.r
        Q[i, j] = Q[j, i] = row.q
    print(tests[["a", "b", "r", "n", "p", "q", "status"]].to_string(index=False))
    fig, ax = plt.subplots(figsize=(12, 10))
    im = ax.imshow(R, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(n)); ax.set_yticks(range(n))
    ax.set_xticklabels(names, rotation=45, ha="right"); ax.set_yticklabels(names)
    for i in range(n):
        for j in range(n):
            label = f"{R[i, j]:+.2f}" + ("*" if Q[i, j] < .05 else "") if np.isfinite(R[i, j]) else "N/A"
            ax.text(j, i, label, ha="center", va="center", fontsize=8,
                    color="white" if np.isfinite(R[i, j]) and abs(R[i, j]) > .65 else "black")
    plt.colorbar(im, label="Pearson r after regime detrending on observed overlap")
    ax.set_title(f"Prespecified 10-indicator annual matrix, requested 1900–{end}\n"
                 "* = BH q<0.05 across 45 pairs, using 3/5/10-year blocks; N/A = insufficient coverage")
    plt.tight_layout(); plt.savefig(out / "18_cross_correlation_matrix.png", dpi=120); plt.close()
    return tests.p.tolist(), [(row.a, row.b, row.r) for row in tests.itertuples()]


# ============================================================
# 4. FDR (BENJAMINI-HOCHBERG)
# ============================================================

def benjamini_hochberg(pvalues, alpha=0.05):
    q = bh_adjust(pvalues)
    return q < alpha, q


def run_fdr_section(pvals, pairs):
    print("\n" + "=" * 80)
    print("4. FDR across all planned pairs, including unavailable tests")
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
        sig = "unavail" if not np.isfinite(pvals[idx]) else "**" if rejected[idx] else "ns"
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
    ap.add_argument("--year-hi", type=int, default=END_YEAR)
    ap.add_argument("--n-boot", type=int, default=20000)
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    run_bootstrap_section(args)
    run_leverage_section(args)
    pvals, pairs = run_cross_corr_matrix(args, out)
    run_fdr_section(pvals, pairs)


if __name__ == "__main__":
    main()
