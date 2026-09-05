"""
Descriptive high-composite runs using fixed composite method v2.

Indicators are standardized to 1985–2010, averaged within six fixed domains,
then domains receive equal weight. M8 is a control only. All fixed members
must be observed; missing years break runs. Full trailing windows prevent
future-data leakage. Default threshold 0.25 is an arbitrary descriptive
composite level, not a sigma level or calibrated significance threshold.
Selected-run trends are exploratory; original historical predictions remain
frozen separately and cannot be evaluated by silently changing methods.
"""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statistical_helpers import baseline_z_score, domain_composite, last_complete_year, residual_slope_ci

from correlate_events import (
    load_yearly_quakes_m7,
    load_yearly_quakes_m8,
    load_yearly_flares_x1,
    load_yearly_war_deaths_split,
    load_yearly_famine_deaths_wpf,
    load_yearly_flood_deaths,
    load_yearly_pandemic_deaths,
    load_yearly_volcanoes,
    load_yearly_cyclone_deaths,
    load_yearly_drought_affected,
    load_yearly_refugee_displaced,
    load_yearly_economic_crises,
    load_yearly_coups,
    load_yearly_terrorism_deaths,
    load_yearly_stock_drawdown_intensity,
)


def z_score(s):
    return baseline_z_score(s)


def find_contractions(rolling_z, threshold=0.25, min_duration=3):
    """Find observed consecutive high runs; missing years break a run."""
    if rolling_z.empty:
        return []
    series = rolling_z.sort_index().reindex(range(int(rolling_z.index.min()), int(rolling_z.index.max()) + 1))
    high = series.notna() & (series > threshold)
    cuts = np.flatnonzero(np.diff(np.r_[False, high.to_numpy(), False]))
    contractions = []
    for start, end in zip(cuts[::2], cuts[1::2]):
        if end - start < min_duration:
            continue
        sub = series.iloc[start:end]
        contractions.append(dict(start=int(sub.index.min()), end=int(sub.index.max()),
                                 duration=len(sub), peak_z=float(sub.max()), peak_year=int(sub.idxmax()),
                                 area_above_baseline=float((sub - threshold).sum())))
    return contractions


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eq-db-1900", default="../earthquakes/quakes_1900.sqlite")
    ap.add_argument("--flares-csv", default="data/flares_xclass.csv")
    ap.add_argument("--wars-csv", default="data/wars.csv")
    ap.add_argument("--floods-csv", default="data/floods.csv")
    ap.add_argument("--famines-wpf-csv", default="data/famine_deaths_by_year.csv")
    ap.add_argument("--pandemics-csv", default="data/pandemics.csv")
    ap.add_argument("--volcanoes-csv", default="data/volcanoes.csv")
    ap.add_argument("--cyclones-csv", default="data/cyclones.csv")
    ap.add_argument("--droughts-csv", default="data/droughts.csv")
    ap.add_argument("--refugees-csv", default="data/refugees.csv")
    ap.add_argument("--economic-csv", default="data/economic_crises.csv")
    ap.add_argument("--coups-csv", default="data/coups.csv")
    ap.add_argument("--terrorism-csv", default="data/terrorism.csv")
    ap.add_argument("--crashes-csv", default="data/stock_crashes.csv")
    ap.add_argument("--threshold", type=float, default=0.25)
    ap.add_argument("--rolling", type=int, default=5)
    ap.add_argument("--min-duration", type=int, default=3)
    ap.add_argument("--year-hi", type=int, default=last_complete_year())
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    indicators = [
        ("M>=7 quakes",
            load_yearly_quakes_m7(args.eq_db_1900, 1900, args.year_hi)),
        ("M>=8 quakes",
            load_yearly_quakes_m8(args.eq_db_1900, 1900, args.year_hi)),
        ("VEI>=5 eruptions",
            load_yearly_volcanoes(args.volcanoes_csv, 1900, args.year_hi, vei_min=5)),
        ("X1+ flares",
            load_yearly_flares_x1(args.flares_csv, 1976, args.year_hi)),
        ("Interstate (basileia) deaths log10",
            np.log10(load_yearly_war_deaths_split(args.wars_csv, "interstate", 1900, args.year_hi) + 1)),
        ("Intrastate (ethnos) deaths log10",
            np.log10(load_yearly_war_deaths_split(args.wars_csv, "intrastate", 1900, args.year_hi) + 1)),
        ("Famine deaths log10",
            np.log10(load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, args.year_hi) + 1)),
        ("Pandemic deaths log10",
            np.log10(load_yearly_pandemic_deaths(args.pandemics_csv, 1900, args.year_hi) + 1)),
        ("Flood deaths log10",
            np.log10(load_yearly_flood_deaths(args.floods_csv, 1985, args.year_hi) + 1)),
        ("Cyclone deaths log10",
            np.log10(load_yearly_cyclone_deaths(args.cyclones_csv, 1950, args.year_hi) + 1)),
        ("Drought affected-population allocation log10",
            np.log10(load_yearly_drought_affected(args.droughts_csv, 1850, args.year_hi) + 1)),
        ("Refugees log10",
            np.log10(load_yearly_refugee_displaced(args.refugees_csv, 1947, args.year_hi) + 1)),
        ("Economic crises",
            load_yearly_economic_crises(args.economic_csv, 1800, args.year_hi)),
        ("Coups",
            load_yearly_coups(args.coups_csv, 1950, args.year_hi)),
        ("Terrorism deaths log10",
            np.log10(load_yearly_terrorism_deaths(args.terrorism_csv, 1970, args.year_hi) + 1)),
        ("Stock crash intensity log10",
            np.log10(load_yearly_stock_drawdown_intensity(args.crashes_csv, 1900, args.year_hi) + 1)),
    ]

    common_years = np.arange(1900, args.year_hi + 1)
    standardized, domains, summary = domain_composite(indicators, common_years)
    Z = standardized.to_numpy().T
    consensus = summary.composite.to_numpy()
    summary.to_csv(out / "22_composite.csv")
    domains.to_csv(out / "22_domains.csv", index_label="year")
    (out / "22_composite.json").write_text(json.dumps(summary.attrs, indent=2))
    consensus_series = summary.composite
    rolling = consensus_series.rolling(args.rolling, min_periods=args.rolling).mean()

    contractions = find_contractions(rolling,
                                        threshold=args.threshold,
                                        min_duration=args.min_duration)

    if summary.eligible.any():
        print(f"Detected {len(contractions)} descriptive runs (trailing {args.rolling}-year mean > {args.threshold}):")
    else:
        print("Contraction detection unavailable: no eligible composite observations.")
    print(f"  {'#':>2}  {'years':<14} {'dur':>4} {'peak_z':>7} {'peak_yr':>8} {'area':>6}")
    print("  " + "-" * 55)
    for i, c in enumerate(contractions, start=1):
        print(f"  {i:>2}  {c['start']}-{c['end']:<8} {c['duration']:>4} "
                f"{c['peak_z']:>7.3f} {c['peak_year']:>8} {c['area_above_baseline']:>6.2f}")

    (out / "22_contractions_results.json").write_text(json.dumps({"method": summary.attrs, "rolling": args.rolling, "threshold": args.threshold, "runs": contractions}, indent=2))
    if not summary.eligible.any():
        print("COMPOSITE UNAVAILABLE: " + summary.attrs["unavailable_reason"])

    # Tests
    if len(contractions) >= 3:
        idx = np.arange(len(contractions))
        peaks = np.array([c["peak_z"] for c in contractions])
        durations = np.array([c["duration"] for c in contractions])
        areas = np.array([c["area_above_baseline"] for c in contractions])

        def slope_ci(y):
            return residual_slope_ci(np.arange(len(y)), y)


        ps, pl, ph = slope_ci(peaks)
        ds, dl, dh = slope_ci(durations)
        as_, al, ah = slope_ci(areas)

        print(f"\nExploratory selected-run trends (n_contractions = {len(contractions)}):")
        print(f"  Peak z trend per contraction: {ps:+.3f} [{pl:+.3f}, {ph:+.3f}]")
        print(f"  Duration trend (yr/contraction): {ds:+.3f} [{dl:+.3f}, {dh:+.3f}]")
        print(f"  Area-above-baseline trend: {as_:+.3f} [{al:+.3f}, {ah:+.3f}]")

        if len(contractions) >= 2:
            gaps = []
            for i in range(1, len(contractions)):
                gaps.append(contractions[i]["start"] - contractions[i - 1]["end"])
            gaps = np.array(gaps)
            print(f"  Gaps between contractions (years): {gaps.tolist()}")
            if len(gaps) >= 3:
                gs, gl, gh = slope_ci(gaps)
                print(f"  Gap-shrinking trend (yr per next gap): "
                        f"{gs:+.3f} [{gl:+.3f}, {gh:+.3f}]")
    else:
        ps = pl = ph = ds = dl = dh = as_ = al = ah = gs = gl = gh = np.nan
        gaps = []

    # ---- Figure ----
    fig, axes = plt.subplots(2, 1, figsize=(15, 9),
                                gridspec_kw={"height_ratios": [3, 2]})
    # Note: do NOT share x — top is year axis, bottom is categorical contraction index.
    # Top: smoothed consensus line with contractions shaded
    ax = axes[0]
    ax.plot(common_years, consensus, color="#cccccc", linewidth=0.8,
              label="Yearly composite v2")
    ax.plot(rolling.index, rolling.values, color="#aa3322", linewidth=2.2,
              label=f"{args.rolling}-yr trailing rolling mean")
    if not summary.eligible.any():
        import textwrap
        ax.text(0.5, 0.65, "Composite unavailable: incomplete fixed panel\n" +
                "\n".join(textwrap.wrap(summary.attrs["unavailable_reason"], 105)),
                transform=ax.transAxes, ha="center", va="center", fontsize=9,
                bbox=dict(facecolor="white", edgecolor="gray", alpha=.95))
    ax.axhline(0, color="black", linewidth=0.7)
    ax.axhline(args.threshold, color="grey", linewidth=0.8, linestyle="--",
                  label=f"contraction threshold = {args.threshold}")
    for c in contractions:
        ax.axvspan(c["start"], c["end"], color="#aa3322", alpha=0.18)
        ax.annotate(f"#{contractions.index(c)+1}\npeak {c['peak_z']:.2f}\n({c['peak_year']})",
                       ((c["start"] + c["end"]) / 2, c["peak_z"] + 0.12),
                       ha="center", fontsize=8.5, alpha=0.9)
    ax.set_ylabel("Composite v2 (equal domain mean)")
    ax.set_xlabel("Year")
    ax.set_xlim(common_years[0], common_years[-1])
    ax.set_title("Contraction periods: continuous stretches where many indicators run hot together",
                  fontsize=12)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="y", alpha=0.3)

    # Bottom: peak intensity bar chart per contraction
    ax = axes[1]
    if not contractions:
        ax.axis("off")
        ax.text(0.5, 0.5, "Run trends unavailable: complete baseline coverage required." if not summary.eligible.any() else "No observed runs meet configured duration and threshold.", transform=ax.transAxes, ha="center", va="center", fontsize=12)
    if contractions:
        x = np.arange(len(contractions))
        labels = [f"#{i+1}\n{c['start']}-{c['end']}" for i, c in enumerate(contractions)]
        peaks = [c["peak_z"] for c in contractions]
        durations = [c["duration"] for c in contractions]
        bars = ax.bar(x - 0.2, peaks, width=0.4, color="#aa3322", alpha=0.85,
                         label="Peak rolling z")
        ax2 = ax.twinx()
        bars2 = ax2.bar(x + 0.2, durations, width=0.4, color="#3366aa", alpha=0.85,
                            label="Duration (yr)")
        ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=9)
        ax.set_ylabel("Peak rolling consensus z", color="#aa3322")
        ax2.set_ylabel("Duration (years)", color="#3366aa")
        ax.tick_params(axis="y", labelcolor="#aa3322")
        ax2.tick_params(axis="y", labelcolor="#3366aa")
        title_parts = []
        if not np.isnan(ps):
            sig = "**" if (pl > 0) or (ph < 0) else ""
            title_parts.append(f"peak trend {ps:+.2f}/contraction [{pl:+.2f}, {ph:+.2f}]{sig}")
        if len(gaps) >= 3 and not np.isnan(gs):
            sig = "**" if (gl > 0) or (gh < 0) else ""
            title_parts.append(f"gap trend {gs:+.1f} yr/contraction [{gl:+.1f}, {gh:+.1f}]{sig}")
        ax.set_title("Per-contraction intensity and duration  |  " + "  |  ".join(title_parts),
                       fontsize=11)

    plt.tight_layout()
    plt.savefig(out / "22_contractions.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'22_contractions.png'}")


if __name__ == "__main__":
    main()
