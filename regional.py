"""
Regional disaggregation: test whether the drought-×-11y-cycle peak is global
or concentrated in specific regions.

The paleoclimate literature suggests the solar-cycle modulation of drought
acts strongest in regions sensitive to jet-stream / ENSO position:
  - Western North America (Pacific Decadal Oscillation)
  - Mexico / Mesoamerica
  - East Africa / Horn of Africa
  - South Asia (monsoon variability)

Method: split the droughts catalog by region, compute periodogram for each,
report the 9-13y peak power/null per region.
"""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from periodogram_extended import raw_periodogram, bootstrap_null


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--droughts-csv", default="data/droughts.csv")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.droughts_csv)
    df["start_year"] = pd.to_numeric(df["start_year"], errors="coerce")
    df["end_year"] = pd.to_numeric(df["end_year"], errors="coerce").fillna(df["start_year"])
    df["deaths_estimate"] = pd.to_numeric(df["deaths_estimate"], errors="coerce").fillna(0)
    df["people_affected"] = pd.to_numeric(df["people_affected"], errors="coerce").fillna(0)
    df["intensity"] = df[["deaths_estimate", "people_affected"]].max(axis=1)

    # Define region buckets — group small regions together where physically sensible
    region_map = {
        "Africa (Sahel + East)": ["Africa", "Horn of Africa"],
        "North America (incl Mexico)": ["North America", "Central America", "Mesoamerica"],
        "South Asia (monsoon)": ["South Asia"],
        "East Asia": ["East Asia"],
        "Europe (Western/Eastern/N)": ["Western Europe", "Europe", "Eastern Europe", "Northern Europe"],
        "Russia / Central Asia": ["Russia", "Central Asia"],
        "South America": ["South America"],
        "Middle East / Levant": ["Levant", "Middle East", "Israel/Phoenicia", "Eastern Mediterranean"],
    }

    common_periods = np.logspace(np.log10(2.5), np.log10(60), 100)
    common_freqs = 1.0 / common_periods

    print(f"{'Region':<30} {'n_events':>9} {'peak period (9-13y)':>22} {'power/null':>12}")
    print("-" * 78)

    results = []
    for region_name, region_list in region_map.items():
        sub = df[(df["region"].isin(region_list)) & (df["start_year"].between(1500, 2025))]
        if len(sub) < 5:
            print(f"  {region_name:<28}  {len(sub):>9}  insufficient data")
            continue

        # Build yearly intensity series 1500-2025
        years = np.arange(1500, 2026)
        out_y = np.zeros(len(years))
        for _, row in sub.iterrows():
            s = int(max(row["start_year"], 1500)); e = int(min(row["end_year"], 2025))
            if e < 1500 or s > 2025 or row["intensity"] == 0:
                continue
            dur = e - s + 1
            per_year = row["intensity"] / dur
            out_y[s - 1500:e - 1500 + 1] += per_year
        log_y = np.log10(out_y + 1)

        freqs, power = raw_periodogram(log_y)
        if len(freqs) < 4:
            continue
        null = bootstrap_null(log_y, n_boot=args.n_boot)
        # 9-13y band
        f = freqs[1:]; p = power[1:]; nl = null[1:]
        per = 1.0 / f
        band = (per >= 9) & (per <= 13)
        if band.sum() == 0:
            continue
        ratio_in_band = (p / np.maximum(nl, 1e-10))[band]
        peak_idx = np.argmax(ratio_in_band)
        peak_per = per[band][peak_idx]
        peak_ratio = ratio_in_band[peak_idx]

        results.append({
            "region": region_name,
            "n_events": len(sub),
            "peak_period": peak_per,
            "peak_ratio": peak_ratio,
        })
        print(f"  {region_name:<28}  {len(sub):>9}  {peak_per:>21.1f}y  {peak_ratio:>11.3f}")

    # ---- Figure ----
    if not results:
        print("No regions had enough data.")
        return
    fig, ax = plt.subplots(figsize=(11, 5))
    names = [r["region"] for r in results]
    ratios = [r["peak_ratio"] for r in results]
    colors = ["#cc4422" if r >= 1.0 else "#888888" for r in ratios]
    y_pos = np.arange(len(names))
    ax.barh(y_pos, ratios, color=colors, edgecolor="black", alpha=0.85)
    ax.axvline(1.0, color="black", linewidth=1, linestyle="--", label="null bound = 1.0")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("9-13y band peak power / bootstrap null")
    ax.set_title("Regional drought periodograms: which regions carry the solar-cycle signal?\n"
                  "Red bars (≥1.0) indicate real 11y peak in that region",
                  fontsize=11)
    ax.legend(loc="lower right", fontsize=9)
    for i, r in enumerate(results):
        ax.text(r["peak_ratio"] + 0.1, i, f"{r['peak_period']:.1f}y (n={r['n_events']})",
                  va="center", fontsize=8.5, alpha=0.8)
    plt.tight_layout()
    plt.savefig(out / "29_regional_drought_periodograms.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'29_regional_drought_periodograms.png'}")


if __name__ == "__main__":
    main()
