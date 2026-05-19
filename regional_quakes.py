"""
Regional disaggregation of M≥7 earthquake rates.

The global M≥7 finding is "barely-significantly rising at +1.7%/decade" — a
weak modern uptick that the M≥8 control says is mostly catalog completeness.
This script asks: does any tectonic region carry a real signal that the
global aggregate is hiding?

Method:
1. Bin NGDC quakes by NOAA `regionCode` and aggregate into tectonic groups.
2. For each region, compute:
   - M≥7 annual count series (1900-2005, the NGDC modern era)
   - Slope per decade with bootstrap CI
   - 9-13y band peak power vs bootstrap null (does the solar cycle show up
     anywhere it doesn't globally?)
3. Plot trend + 11y peak by region.

NOAA regionCode mapping (verified empirically):
   10  Africa
   20  Antarctica
   30  East Asia (Japan, China, Taiwan, Korea, Philippines coast)
   40  Central Asia (Afghanistan, Tajikistan, Armenia)
   50  E Russia / Kamchatka
   60  Indonesia / South Asia (Indonesia, India, Pakistan, Myanmar, Bangladesh)
   70  Atlantic (Azores, mid-Atlantic, S Atlantic)
   90  Caribbean (DR, Jamaica, Haiti, Venezuela)
   100 Central America
   110 (small)
   120 Western Europe (France, Switzerland, Iceland)
   130 Eastern Mediterranean (Italy, Greece, Albania)
   140 Middle East (Iran, Turkey, Syria)
   150 N South America (Andean)
   160 S South America (Chile)
   170 Oceania (PNG, Fiji, Tonga, NZ)

Tectonic groups:
   Pacific Ring of Fire:  {30, 50, 100, 150, 160, 170}
   Alpide belt (Med-Himalayan): {40, 120, 130, 140}
   Indo-Asian (subduction + Himalaya mix): {60}
   Caribbean subduction:  {90}
   Atlantic / MOR:        {70}
   African / rift:        {10}

Reads NGDC catalog (data/noaa_significant_earthquakes.csv), writes
figures/33_regional_quakes.png.
"""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from periodogram_extended import raw_periodogram, bootstrap_null


REGION_GROUPS = {
    "Pacific Ring of Fire":        [30, 50, 100, 150, 160, 170],
    "Alpide (Med-to-Himalayan)":   [40, 120, 130, 140],
    "Indo-Asian (Indonesia+India)": [60],
    "Caribbean subduction":        [90],
    "Atlantic / MOR":              [70],
    "African / rift":              [10],
}


def fit_slope_bootstrap(years: np.ndarray, values: np.ndarray, n_boot=2000,
                          rng=None):
    """OLS slope per decade with bootstrap CI."""
    rng = rng or np.random.default_rng(42)
    if len(years) < 5:
        return {"slope_per_decade": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "mean": 0.0}
    a, b = np.polyfit(years, values, 1)
    slopes = []
    n = len(years)
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        try:
            ai, _ = np.polyfit(years[idx], values[idx], 1)
            slopes.append(ai)
        except Exception:
            continue
    slopes = np.array(slopes)
    return {
        "slope_per_decade": float(a) * 10.0,
        "ci_lo": float(np.percentile(slopes, 2.5)) * 10.0,
        "ci_hi": float(np.percentile(slopes, 97.5)) * 10.0,
        "mean": float(values.mean()),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--noaa-quakes-csv", default="data/noaa_significant_earthquakes.csv")
    ap.add_argument("--mag-min", type=float, default=7.0)
    ap.add_argument("--year-lo", type=int, default=1900)
    ap.add_argument("--year-hi", type=int, default=2005)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.noaa_quakes_csv)
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["eqMagnitude"] = pd.to_numeric(df["eqMagnitude"], errors="coerce")
    df["regionCode"] = pd.to_numeric(df["regionCode"], errors="coerce")
    df = df[(df["eqMagnitude"] >= args.mag_min)
              & df["year"].between(args.year_lo, args.year_hi)
              & df["regionCode"].notna()]
    print(f"Filtered to {len(df)} events: M≥{args.mag_min}, {args.year_lo}-{args.year_hi}")

    years = np.arange(args.year_lo, args.year_hi + 1)
    results = []

    # Global baseline first
    yc_global = df.groupby(df["year"].astype(int)).size().reindex(years, fill_value=0)
    trend = fit_slope_bootstrap(years.astype(float), yc_global.values.astype(float),
                                  n_boot=args.n_boot)
    freqs, power = raw_periodogram(yc_global.values.astype(float))
    null = bootstrap_null(yc_global.values.astype(float), n_boot=args.n_boot)
    f = freqs[1:]; p = power[1:]; nl = null[1:]
    per = 1.0 / f
    band = (per >= 9) & (per <= 13)
    if band.sum() > 0:
        ratio_in_band = (p / np.maximum(nl, 1e-10))[band]
        peak_idx = np.argmax(ratio_in_band)
        peak_per = per[band][peak_idx]
        peak_ratio = ratio_in_band[peak_idx]
    else:
        peak_per, peak_ratio = np.nan, np.nan
    results.append({
        "region": "GLOBAL (all regions)", "n": len(df), "series": yc_global,
        "slope_per_decade": trend["slope_per_decade"],
        "ci_lo": trend["ci_lo"], "ci_hi": trend["ci_hi"],
        "mean": trend["mean"], "peak_per": peak_per, "peak_ratio": peak_ratio,
    })

    for name, codes in REGION_GROUPS.items():
        sub = df[df["regionCode"].isin(codes)]
        if len(sub) < 15:
            print(f"  {name:<32}  n={len(sub):>4}  insufficient")
            continue
        yc = sub.groupby(sub["year"].astype(int)).size().reindex(years, fill_value=0)
        trend = fit_slope_bootstrap(years.astype(float), yc.values.astype(float),
                                      n_boot=args.n_boot)
        freqs, power = raw_periodogram(yc.values.astype(float))
        null = bootstrap_null(yc.values.astype(float), n_boot=args.n_boot)
        f = freqs[1:]; p = power[1:]; nl = null[1:]
        per = 1.0 / f
        band = (per >= 9) & (per <= 13)
        if band.sum() > 0:
            ratio_in_band = (p / np.maximum(nl, 1e-10))[band]
            peak_idx = np.argmax(ratio_in_band)
            peak_per = per[band][peak_idx]
            peak_ratio = ratio_in_band[peak_idx]
        else:
            peak_per, peak_ratio = np.nan, np.nan
        results.append({
            "region": name, "n": len(sub), "series": yc,
            "slope_per_decade": trend["slope_per_decade"],
            "ci_lo": trend["ci_lo"], "ci_hi": trend["ci_hi"],
            "mean": trend["mean"],
            "peak_per": peak_per, "peak_ratio": peak_ratio,
        })

    print(f"\n{'Region':<32} {'n':>5} {'slope/dec':>10} {'95% CI':>22} "
            f"{'mean/yr':>8} {'peak P':>8} {'P/null':>8}")
    print("-" * 100)
    for r in results:
        ci = f"[{r['ci_lo']:+.3f}, {r['ci_hi']:+.3f}]"
        print(f"  {r['region']:<30}  {r['n']:>5}  {r['slope_per_decade']:+10.3f}  "
                f"{ci:>22}  {r['mean']:>7.2f}  {r['peak_per']:>6.1f}y  {r['peak_ratio']:>8.3f}")

    # ---- Figure: 2-panel (trend slopes + 11y peak ratios) ----
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    names = [r["region"] for r in results]
    slopes = [r["slope_per_decade"] for r in results]
    ci_lo = [r["ci_lo"] for r in results]
    ci_hi = [r["ci_hi"] for r in results]
    ratios = [r["peak_ratio"] for r in results]
    peak_pers = [r["peak_per"] for r in results]

    # Color: red if trend significantly above 0, green if significantly below, grey otherwise
    colors_trend = []
    for r in results:
        if r["ci_lo"] > 0:
            colors_trend.append("#cc4422")
        elif r["ci_hi"] < 0:
            colors_trend.append("#22aa44")
        else:
            colors_trend.append("#888888")

    y_pos = np.arange(len(names))
    err_lo = [s - lo for s, lo in zip(slopes, ci_lo)]
    err_hi = [hi - s for s, hi in zip(slopes, ci_hi)]
    ax1.barh(y_pos, slopes, xerr=[err_lo, err_hi], color=colors_trend,
               edgecolor="black", alpha=0.85, capsize=4)
    ax1.axvline(0, color="black", linewidth=0.8)
    ax1.set_yticks(y_pos)
    ax1.set_yticklabels(names, fontsize=9)
    ax1.invert_yaxis()
    ax1.set_xlabel("M≥7 events per year — trend (slope per decade)")
    ax1.set_title(f"Regional trend in M≥7 quakes, {args.year_lo}-{args.year_hi}\n"
                    "Red = significantly rising; green = falling; grey = flat",
                    fontsize=11)
    for i, r in enumerate(results):
        ax1.text(max(slopes[i], 0) + 0.05, i, f"n={r['n']}, mean={r['mean']:.2f}/yr",
                   va="center", fontsize=8, alpha=0.75)

    # Panel 2: 11y peak ratios
    colors_peak = ["#cc4422" if r >= 1.0 else "#888888" for r in ratios]
    ax2.barh(y_pos, ratios, color=colors_peak, edgecolor="black", alpha=0.85)
    ax2.axvline(1.0, color="black", linewidth=1, linestyle="--",
                  label="null bound = 1.0")
    ax2.set_yticks(y_pos)
    ax2.set_yticklabels(names, fontsize=9)
    ax2.invert_yaxis()
    ax2.set_xlabel("9-13y band peak power / bootstrap null")
    ax2.set_title("Regional 11-year-cycle peak in M≥7 quakes\n"
                    "Red bars ≥ 1.0 = 11y signal above noise floor",
                    fontsize=11)
    ax2.legend(loc="lower right", fontsize=9)
    for i, r in enumerate(results):
        if not np.isnan(r["peak_per"]):
            ax2.text(r["peak_ratio"] + 0.05, i,
                       f"{r['peak_per']:.1f}y peak",
                       va="center", fontsize=8, alpha=0.75)

    fig.suptitle(
        "Does any tectonic region carry an earthquake signal the global "
        "aggregate hides?  Spoiler: the trend story varies by region; the "
        "11y story stays null everywhere.",
        fontsize=12, y=1.00)
    plt.tight_layout(rect=(0, 0, 1, 0.96))
    plt.savefig(out / "33_regional_quakes.png", dpi=120, bbox_inches="tight")
    plt.close()
    print(f"\nWrote {out/'33_regional_quakes.png'}")


if __name__ == "__main__":
    main()
