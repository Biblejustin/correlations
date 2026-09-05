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
import contextlib
import io
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import grangercausalitytests, adfuller
from statsmodels.tools.sm_exceptions import InfeasibleTestError

from correlate_events import (
    load_yearly_war_deaths_active,
    load_yearly_war_deaths_split,
    load_yearly_famine_deaths_wpf,
)
from detection_regimes import REGIMES, piecewise_detrend
from statistical_helpers import contiguous_overlap, bh_adjust, last_complete_year


def run_granger(x, y, max_lag, label_x, label_y):
    """Test whether x Granger-causes y. Returns dict of p-values per lag."""
    df = pd.DataFrame({"x": x, "y": y})
    try:
        df = contiguous_overlap(df, min_years=3 * max_lag + 2)
    except ValueError:
        return None
    if (df.std() == 0).any():
        return None
    # Test: does x help predict y? Statsmodels expects y in first column.
    pvals_xy = {}
    with contextlib.redirect_stdout(io.StringIO()):
        res = grangercausalitytests(df[["y", "x"]], maxlag=max_lag)
    for lag, info in res.items():
        # Use the F-test p-value (params_ftest)
        pvals_xy[lag] = info[0]["params_ftest"][1]
    return pvals_xy


def granger_family(wars, interstate, intrastate, famines, max_lag=5):
    """One shared observed annual panel, all six directions and lag orders."""
    aligned = contiguous_overlap({"combined": wars, "interstate": interstate,
                                  "intrastate": intrastate, "famines": famines},
                                 min_years=3 * max_lag + 2)
    rows = []
    for label, key in [("Wars (combined)", "combined"),
                       ("Interstate (basileia)", "interstate"),
                       ("Intrastate (ethnos)", "intrastate")]:
        for src, dst, direction in [(key, "famines", f"{label} → Famines"),
                                    ("famines", key, f"Famines → {label}")]:
            try:
                p = run_granger(aligned[src], aligned[dst], max_lag, src, dst)
            except (ValueError, np.linalg.LinAlgError, InfeasibleTestError):
                p = None
            for lag in range(1, max_lag + 1):
                rows.append(dict(direction=direction, lag_order=lag,
                                 p=float(p[lag]) if p else np.nan, n=len(aligned),
                                 start_year=int(aligned.index.min()), end_year=int(aligned.index.max())))
    result = pd.DataFrame(rows)
    result["q"] = bh_adjust(result["p"])
    result["fdr_significant"] = result["q"] < 0.05
    result["family_size"] = len(result)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wars-csv", default="data/wars.csv")
    ap.add_argument("--famines-wpf-csv", default="data/famine_deaths_by_year.csv")
    ap.add_argument("--max-lag", type=int, default=5)
    ap.add_argument("--year-hi", type=int, default=last_complete_year())
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    # Load 1900 through requested complete-year cutoff, log-transform, regime-detrend
    yr_lo, yr_hi = 1900, args.year_hi
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
    print("Augmented Dickey-Fuller stationarity tests (p < 0.05 rejects a unit-root null):")
    for name, s in [("Wars (combined, detrended)", wars_d),
                       ("Wars (interstate, detrended)", wars_inter_d),
                       ("Wars (intrastate, detrended)", wars_intra_d),
                       ("Famine deaths (detrended)", famines_d)]:
        try:
            stat, p, *_ = adfuller(s.values)
            print(f"  {name:<35} ADF p = {p:.4f}  {'reject unit root' if p < 0.05 else 'unit root not rejected'}")
        except Exception as e:
            print(f"  {name}: ADF failed ({e})")

    family = granger_family(wars_d, wars_inter_d, wars_intra_d, famines_d, args.max_lag)
    family.to_csv(out / "28_granger_results.csv", index=False)
    print("\nGranger model orders jointly include lags 1..k; full-family BH correction:")
    print(family.to_string(index=False))
    print(f"FDR survivors: {family.fdr_significant.sum()}/{len(family)}. Predictive association does not establish causation or directional asymmetry.")
    results = {label: dict(zip(frame.lag_order, frame.q))
               for label, frame in family.groupby("direction", sort=False)}

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
    ax.set_xlabel("Model lag order k (joint test of years 1..k)")
    ax.set_ylabel("BH q-value across all directions and orders")
    ax.set_yscale("log")
    ax.set_title("Exploratory Granger prediction tests: wars and famines\n"
                  "Below line = FDR survivor under fitted model assumptions",
                  fontsize=11)
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(out / "28_granger_wars_famines.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'28_granger_wars_famines.png'}")


if __name__ == "__main__":
    main()
