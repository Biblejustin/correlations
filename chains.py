"""
Exploratory cross-category lag scans, from -2 through +10 years.

Moving-block confidence intervals describe fixed lags. Circular-shift tests
preserve each residual series' temporal ordering and repeat the entire lag
search. BH correction covers all 8x13 pointwise tests; a second, clearly
labelled family adjusts 8 selected chain maxima. Neither implies causation.
Drought affected-population allocations are impact proxies, not measurements
of physical drought severity; missing estimates remain unavailable.
"""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from correlate_events import (
    load_yearly_war_deaths_active,
    load_yearly_war_deaths_split,
    load_yearly_famine_deaths_wpf,
    load_yearly_flood_deaths,
    load_yearly_drought_affected,
    load_yearly_volcanoes,
    load_yearly_refugee_displaced,
    load_yearly_economic_crises,
    load_yearly_coups,
)
from detection_regimes import REGIMES, piecewise_detrend
from statistical_helpers import contiguous_overlap, block_indices, bh_adjust, last_complete_year


def _lag_pair(x, y, lag):
    if lag > 0:
        return x[:-lag], y[lag:]
    if lag < 0:
        return x[-lag:], y[:lag]
    return x, y


def _correlation(x, y):
    if len(x) < 8 or np.std(x) <= 1e-12 or np.std(y) <= 1e-12:
        return np.nan
    return float(np.corrcoef(x, y)[0, 1])


def lag_correlation_bootstrap(a, b, lags, regime_a, regime_b, n_boot=1000, seed=42):
    """Exploratory lag scan with block intervals and a persistence-aware null.

    Circular shifts of one complete annual residual series preserve its
    autocorrelation. Each shift repeats the full lag search. Pointwise CIs
    describe fixed lags; selected peaks require p_lag_search and family q.
    Shift inference assumes approximate stationarity after regime detrending.
    """
    rng = np.random.default_rng(seed)
    try:
        frame = contiguous_overlap({"a": a, "b": b}, min_years=max(20, 8 + max(abs(l) for l in lags)))
    except ValueError as exc:
        return pd.DataFrame([dict(lag=lag, r=np.nan, ci_lo=np.nan, ci_hi=np.nan,
                                  n=0, p=np.nan, p_lag_search=np.nan, status=str(exc)) for lag in lags])
    x = piecewise_detrend(frame.a, REGIMES.get(regime_a, [])).to_numpy()
    y = piecewise_detrend(frame.b, REGIMES.get(regime_b, [])).to_numpy()
    # Enumerate every nonidentity circular shift: reproducible exact shift orbit.
    null = np.asarray([[_correlation(*_lag_pair(x, np.roll(y, shift), lag))
                        for lag in lags] for shift in range(1, len(x))])
    finite_null = np.isfinite(null).any(axis=1)
    maxima = np.full(len(null), np.nan)
    maxima[finite_null] = np.nanmax(np.abs(null[finite_null]), axis=1)
    rows = []
    for col, lag in enumerate(lags):
        lx, ly = _lag_pair(x, y, lag)
        r = _correlation(lx, ly)
        boots = []
        if np.isfinite(r):
            for _ in range(n_boot):
                idx = block_indices(len(lx), rng)
                rb = _correlation(lx[idx], ly[idx])
                if np.isfinite(rb):
                    boots.append(rb)
        lo, hi = np.percentile(boots, [2.5, 97.5]) if boots else (np.nan, np.nan)
        point_null = np.abs(null[:, col]); point_null = point_null[np.isfinite(point_null)]
        scan_null = maxima[np.isfinite(maxima)]
        p = (1 + np.sum(point_null >= abs(r))) / (len(point_null) + 1) if np.isfinite(r) else np.nan
        p_scan = (1 + np.sum(scan_null >= abs(r))) / (len(scan_null) + 1) if np.isfinite(r) else np.nan
        rows.append(dict(lag=lag, r=r, ci_lo=lo, ci_hi=hi, n=len(lx), p=p,
                         p_lag_search=p_scan, block_length=int(np.ceil(len(lx) ** (1/3))),
                         start_year=int(frame.index.min()), end_year=int(frame.index.max()),
                         n_shifts=len(null), status="exploratory"))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wars-csv", default="data/wars.csv")
    ap.add_argument("--floods-csv", default="data/floods.csv")
    ap.add_argument("--famines-wpf-csv", default="data/famine_deaths_by_year.csv")
    ap.add_argument("--droughts-csv", default="data/droughts.csv")
    ap.add_argument("--volcanoes-csv", default="data/volcanoes.csv")
    ap.add_argument("--refugees-csv", default="data/refugees.csv")
    ap.add_argument("--economic-csv", default="data/economic_crises.csv")
    ap.add_argument("--coups-csv", default="data/coups.csv")
    ap.add_argument("--year-hi", type=int, default=last_complete_year())
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    yr_lo, yr_hi = 1900, args.year_hi
    wars = np.log10(load_yearly_war_deaths_active(args.wars_csv, yr_lo, yr_hi) + 1)
    wars_inter = np.log10(load_yearly_war_deaths_split(args.wars_csv, "interstate", yr_lo, yr_hi) + 1)
    wars_intra = np.log10(load_yearly_war_deaths_split(args.wars_csv, "intrastate", yr_lo, yr_hi) + 1)
    famines = np.log10(load_yearly_famine_deaths_wpf(args.famines_wpf_csv, yr_lo, yr_hi) + 1)
    droughts = np.log10(load_yearly_drought_affected(args.droughts_csv, yr_lo, yr_hi) + 1)
    volcs = load_yearly_volcanoes(args.volcanoes_csv, yr_lo, yr_hi, vei_min=5)
    refugees = np.log10(load_yearly_refugee_displaced(args.refugees_csv, 1947, yr_hi) + 1)
    econ = load_yearly_economic_crises(args.economic_csv, yr_lo, yr_hi)
    coups = load_yearly_coups(args.coups_csv, 1950, yr_hi)

    lags = list(range(-2, 11))
    chains = [
        ("Drought affected allocation → Famine deaths", droughts, famines, "droughts", "famines"),
        ("Interstate (basileia) → Famine deaths", wars_inter, famines, "wars_global", "famines"),
        ("Intrastate (ethnos) → Famine deaths", wars_intra, famines, "wars_global", "famines"),
        ("War (combined) → Refugees", wars, refugees, "wars_global", "refugees"),
        ("Intrastate (ethnos) → Refugees", wars_intra, refugees, "wars_global", "refugees"),
        ("Volcano (VEI≥5) → Famine deaths", volcs, famines, "volcanoes", "famines"),
        ("Economic crisis → Coups", econ, coups, "economic_crises", "coups"),
        ("Economic crisis → Intrastate war", econ, wars_intra, "economic_crises", "wars_global"),
    ]

    frames = []
    for name, a, b, ra, rb in chains:
        frame = lag_correlation_bootstrap(a, b, lags, ra, rb, n_boot=args.n_boot)
        frame.insert(0, "chain", name)
        frames.append(frame)
    all_results = pd.concat(frames, ignore_index=True)
    all_results["q_all_lags"] = bh_adjust(all_results.p)
    all_results["family_size"] = len(all_results)
    all_results.to_csv(out / "26_chain_results.csv", index=False)
    selected = all_results.dropna(subset=["r"]).groupby("chain", sort=False).apply(
        lambda group: group.loc[group.r.abs().idxmax()], include_groups=False)
    if len(selected):
        # Include unavailable chains in the planned family count.
        selected["q_selected_chain"] = pd.Series(bh_adjust(selected.p_lag_search.reindex([c[0] for c in chains])), index=[c[0] for c in chains]).reindex(selected.index)
        selected.to_csv(out / "26_chain_selected_peaks.csv")
        print("Selected exploratory peaks: block CIs are pointwise; use lag-search p and family q.")
        print(selected[["lag", "r", "ci_lo", "ci_hi", "p_lag_search", "q_selected_chain"]].to_string())
    results = dict((name, frame) for name, frame in all_results.groupby("chain", sort=False))

    # ---- Figure: 4×2 grid ----
    fig, axes = plt.subplots(2, 4, figsize=(20, 8))
    for ax, (name, df) in zip(axes.flat, results.items()):
        ax.errorbar(df["lag"], df["r"],
                      yerr=[np.maximum(0, df["r"] - df["ci_lo"]), np.maximum(0, df["ci_hi"] - df["r"])],
                      fmt="o-", capsize=3, linewidth=1.5)
        if not df.r.notna().any():
            import textwrap
            ax.text(0.5, 0.6, "Unavailable\n" + "\n".join(textwrap.wrap(str(df.status.iloc[0]), 36)), transform=ax.transAxes, ha="center", va="center", fontsize=9)
        ax.axhline(0, color="black", linewidth=0.7)
        ax.set_xlabel("Lag (years; predictor precedes outcome when positive)")
        ax.set_ylabel("Pearson r (detrended)")
        ax.set_title(name, fontsize=10)
        ax.grid(axis="y", alpha=0.3)
        ax.set_xlim(min(lags) - 0.5, max(lags) + 0.5)
    plt.suptitle("Exploratory lag scans — pointwise 95% block intervals; selection-adjusted results in CSV",
                  fontsize=12)
    plt.tight_layout()
    plt.savefig(out / "26_chains.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'26_chains.png'}")


if __name__ == "__main__":
    main()
