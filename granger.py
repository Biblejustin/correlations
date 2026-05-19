"""
Granger causality on the wars↔famines pair (and its ethnos/basileia split).

The wavelet coherence showed when the pair couples; the chains showed at what
lag. Granger causality asks: which direction does the information flow?
  - Does past war activity help predict future famines beyond what famine's
    own past predicts? (war → famine)
  - Does past famine activity help predict future wars? (famine → war)
  - Or both? (bidirectional / instantaneous)

Granger doesn't prove causation but formalizes the temporal precedence test.

Writes figures/28_granger_wars_famines.png and prints a results table.
"""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import grangercausalitytests, adfuller

from correlate_events import (
    load_yearly_war_deaths_active,
    load_yearly_war_deaths_split,
    load_yearly_famine_deaths_wpf,
)
from detection_regimes import REGIMES, piecewise_detrend


def run_granger(x, y, max_lag, label_x, label_y):
    """Test whether x Granger-causes y. Returns dict of p-values per lag."""
    df = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(df) < max_lag + 10:
        return None
    # Test: does x help predict y? Statsmodels expects y in first column.
    pvals_xy = {}
    res = grangercausalitytests(df[["y", "x"]], maxlag=max_lag, verbose=False)
    for lag, info in res.items():
        # Use the F-test p-value (params_ftest)
        pvals_xy[lag] = info[0]["params_ftest"][1]
    return pvals_xy


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wars-csv", default="data/wars.csv")
    ap.add_argument("--famines-wpf-csv", default="data/famine_deaths_by_year.csv")
    ap.add_argument("--max-lag", type=int, default=5)
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    # Load 1900-2025, log-transform, regime-detrend
    yr_lo, yr_hi = 1900, 2025
    wars = np.log10(load_yearly_war_deaths_active(args.wars_csv, yr_lo, yr_hi) + 1)
    wars_inter = np.log10(load_yearly_war_deaths_split(args.wars_csv, "interstate", yr_lo, yr_hi) + 1)
    wars_intra = np.log10(load_yearly_war_deaths_split(args.wars_csv, "intrastate", yr_lo, yr_hi) + 1)
    famines = np.log10(load_yearly_famine_deaths_wpf(args.famines_wpf_csv, yr_lo, yr_hi) + 1)

    # Detrend
    wars_d = piecewise_detrend(wars.astype(float), REGIMES["wars_global"]).dropna()
    wars_inter_d = piecewise_detrend(wars_inter.astype(float), REGIMES["wars_global"]).dropna()
    wars_intra_d = piecewise_detrend(wars_intra.astype(float), REGIMES["wars_global"]).dropna()
    famines_d = piecewise_detrend(famines.astype(float), REGIMES["famines"]).dropna()

    # Stationarity check
    print("Augmented Dickey-Fuller stationarity tests (p < 0.05 means stationary):")
    for name, s in [("Wars (combined, detrended)", wars_d),
                       ("Wars (interstate, detrended)", wars_inter_d),
                       ("Wars (intrastate, detrended)", wars_intra_d),
                       ("Famine deaths (detrended)", famines_d)]:
        try:
            stat, p, *_ = adfuller(s.values)
            print(f"  {name:<35} ADF p = {p:.4f}  {'STATIONARY' if p < 0.05 else 'non-stationary'}")
        except Exception as e:
            print(f"  {name}: ADF failed ({e})")

    # Granger tests in both directions
    print("\nGranger causality tests (F-test p-values per lag):")
    print(f"{'Direction':<55} {'lag=1':>8} {'lag=2':>8} {'lag=3':>8} {'lag=4':>8} {'lag=5':>8}")
    print("-" * 95)
    results = {}
    pairs = [
        ("Wars (combined) → Famines",     wars_d, famines_d),
        ("Famines → Wars (combined)",     famines_d, wars_d),
        ("Interstate (basileia) → Famines", wars_inter_d, famines_d),
        ("Famines → Interstate (basileia)", famines_d, wars_inter_d),
        ("Intrastate (ethnos) → Famines",   wars_intra_d, famines_d),
        ("Famines → Intrastate (ethnos)",   famines_d, wars_intra_d),
    ]
    for label, src, dst in pairs:
        # align both
        common = src.index.intersection(dst.index)
        s = src.loc[common]; d = dst.loc[common]
        p = run_granger(s.values, d.values, args.max_lag, "src", "dst")
        results[label] = p
        if p:
            cells = "  ".join(f"{p[lag]:.4f}" for lag in range(1, args.max_lag + 1))
            print(f"  {label:<55} {cells}")
        else:
            print(f"  {label}: insufficient data")

    # ---- Figure ----
    fig, ax = plt.subplots(figsize=(11, 6))
    lags = np.arange(1, args.max_lag + 1)
    colors = {"Wars (combined) → Famines": "#222222",
                "Famines → Wars (combined)": "#888888",
                "Interstate (basileia) → Famines": "#3366aa",
                "Famines → Interstate (basileia)": "#6688cc",
                "Intrastate (ethnos) → Famines": "#cc4422",
                "Famines → Intrastate (ethnos)": "#dd7766"}
    for label, p in results.items():
        if not p:
            continue
        ax.plot(lags, [p[lag] for lag in lags], "o-", color=colors[label],
                  linewidth=2, markersize=8, label=label)
    ax.axhline(0.05, color="red", linestyle="--", linewidth=1, label="α = 0.05 threshold")
    ax.set_xlabel("Lag (years)")
    ax.set_ylabel("Granger F-test p-value (below 0.05 = significant)")
    ax.set_yscale("log")
    ax.set_title("Granger causality: who leads whom between wars and famines?\n"
                  "Below the red line = X helps predict Y beyond Y's own past at that lag",
                  fontsize=11)
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(out / "28_granger_wars_famines.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'28_granger_wars_famines.png'}")


if __name__ == "__main__":
    main()
