"""
Cross-category chain analyses.

Tests lagged-causal chains across catalogs:

  1. Drought → famine chain: drought intensity year T vs famine deaths year T+0..+5
  2. War → flood-mortality chain: war deaths year T vs flood deaths year T+0..+5
  3. War → refugee chain: war deaths year T vs refugee displaced year T+0..+5
  4. Volcanic cooling → famine chain: VEI≥6 year T vs famine deaths year T+0..+5
  5. Economic crisis → coup chain: economic crisis year T vs coups year T+0..+5

Each chain is tested with a lag scan -2..+10 years and reports the Pearson r
with 95% bootstrap CI at each lag.

Writes figures/26_chains.png.
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
    load_yearly_drought_intensity,
    load_yearly_volcanoes,
    load_yearly_refugee_displaced,
    load_yearly_economic_crises,
    load_yearly_coups,
)
from detection_regimes import REGIMES, piecewise_detrend


def lag_correlation_bootstrap(a, b, lags, regime_a, regime_b, n_boot=1000, seed=42):
    """For each lag, compute Pearson r between a and b shifted by lag,
    plus a bootstrap 95% CI."""
    rng = np.random.default_rng(seed)
    overlap = a.index.intersection(b.index)
    a = a.loc[overlap].astype(float)
    b = b.loc[overlap].astype(float)
    a_d = piecewise_detrend(a, REGIMES.get(regime_a, []))
    b_d = piecewise_detrend(b, REGIMES.get(regime_b, []))

    rows = []
    for lag in lags:
        bs = b_d.shift(-lag)  # negative shift: b at year T+lag aligns with a at year T
        mask = ~(a_d.isna() | bs.isna())
        x = a_d[mask].values; y = bs[mask].values
        if len(x) < 8:
            rows.append({"lag": lag, "r": np.nan, "ci_lo": np.nan, "ci_hi": np.nan,
                          "n": int(len(x))}); continue
        r, _ = stats.pearsonr(x, y)
        boots = []
        for _ in range(n_boot):
            idx = rng.integers(0, len(x), len(x))
            if len(set(idx)) < 3:
                continue
            rb, _ = stats.pearsonr(x[idx], y[idx])
            boots.append(rb)
        lo, hi = np.percentile(boots, [2.5, 97.5])
        rows.append({"lag": lag, "r": r, "ci_lo": lo, "ci_hi": hi, "n": int(len(x))})
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
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    yr_lo, yr_hi = 1900, 2025
    wars = np.log10(load_yearly_war_deaths_active(args.wars_csv, yr_lo, yr_hi) + 1)
    wars_inter = np.log10(load_yearly_war_deaths_split(args.wars_csv, "interstate", yr_lo, yr_hi) + 1)
    wars_intra = np.log10(load_yearly_war_deaths_split(args.wars_csv, "intrastate", yr_lo, yr_hi) + 1)
    famines = np.log10(load_yearly_famine_deaths_wpf(args.famines_wpf_csv, yr_lo, yr_hi) + 1)
    floods = np.log10(load_yearly_flood_deaths(args.floods_csv, yr_lo, yr_hi) + 1)
    droughts = np.log10(load_yearly_drought_intensity(args.droughts_csv, yr_lo, yr_hi) + 1)
    volcs = load_yearly_volcanoes(args.volcanoes_csv, yr_lo, yr_hi, vei_min=5)
    refugees = np.log10(load_yearly_refugee_displaced(args.refugees_csv, 1947, yr_hi) + 1)
    econ = load_yearly_economic_crises(args.economic_csv, yr_lo, yr_hi)
    coups = load_yearly_coups(args.coups_csv, 1950, yr_hi)

    lags = list(range(-2, 11))
    chains = [
        ("Drought → Famine deaths", droughts, famines, "droughts", "famines"),
        ("Interstate (basileia) → Famine deaths", wars_inter, famines, "wars_global", "famines"),
        ("Intrastate (ethnos) → Famine deaths", wars_intra, famines, "wars_global", "famines"),
        ("War (combined) → Refugees", wars, refugees, "wars_global", "refugees"),
        ("Intrastate (ethnos) → Refugees", wars_intra, refugees, "wars_global", "refugees"),
        ("Volcano (VEI≥5) → Famine deaths", volcs, famines, "volcanoes", "famines"),
        ("Economic crisis → Coups", econ, coups, "economic_crises", "coups"),
        ("Economic crisis → Intrastate war", econ, wars_intra, "economic_crises", "wars_global"),
    ]

    results = {}
    print(f"{'Chain':<40} {'best lag':>10} {'peak r':>10} {'95% CI':>22}")
    print("-" * 90)
    for name, a, b, ra, rb in chains:
        df = lag_correlation_bootstrap(a, b, lags, ra, rb)
        results[name] = df
        # find peak
        idx = df["r"].abs().idxmax() if df["r"].notna().any() else None
        if idx is None:
            continue
        row = df.loc[idx]
        ci = f"[{row['ci_lo']:+.3f}, {row['ci_hi']:+.3f}]"
        print(f"{name:<40} {int(row['lag']):>+10d} {row['r']:>+10.3f} {ci:>22}")

    # ---- Figure: 4×2 grid ----
    fig, axes = plt.subplots(2, 4, figsize=(20, 8))
    for ax, (name, df) in zip(axes.flat, results.items()):
        ax.errorbar(df["lag"], df["r"],
                      yerr=[df["r"] - df["ci_lo"], df["ci_hi"] - df["r"]],
                      fmt="o-", capsize=3, linewidth=1.5)
        ax.axhline(0, color="black", linewidth=0.7)
        ax.set_xlabel("Lag (years from cause to effect)")
        ax.set_ylabel("Pearson r (detrended)")
        ax.set_title(name, fontsize=10)
        ax.grid(axis="y", alpha=0.3)
        ax.set_xlim(min(lags) - 0.5, max(lags) + 0.5)
    plt.suptitle("Cross-category chain tests — lagged Pearson r with 95% bootstrap CI",
                  fontsize=12)
    plt.tight_layout()
    plt.savefig(out / "26_chains.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'26_chains.png'}")


if __name__ == "__main__":
    main()
