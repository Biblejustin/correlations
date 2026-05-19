"""
Test the contraction-period hypothesis.

Hypothesis: WW1-era (~1914-1923), WW2-era (~1939-1945), and the modern era
are "contractions" in the birth-pains analogy — multi-year periods where
many disaster indicators are simultaneously elevated, separated by quieter
gaps.

If this is the birth-pains pattern, then:
  - Each successive contraction should be MORE INTENSE than the last
    (peak rolling consensus z increases)
  - Gaps between contractions should be SHRINKING
    (less rest between bursts)
  - Contractions might also be getting LONGER

Method:
  1. Compute the consensus z (mean z-score across all indicators per year).
  2. Apply a 5-year centered rolling mean to smooth out single-year noise.
  3. Identify "contraction periods" as continuous runs where rolling z >
     threshold (0.25 by default — half a standard deviation above the
     all-indicator baseline).
  4. For each contraction: record start/end year, peak rolling z, duration,
     and area-above-baseline.
  5. Test intensification: regress peak z on contraction index.
  6. Test gap-shrinking: regress inter-contraction gap on contraction index.
"""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from correlate_events import (
    load_yearly_quakes_m7,
    load_yearly_quakes_m8,
    load_yearly_flares_x1,
    load_yearly_war_deaths_active,
    load_yearly_famine_deaths_wpf,
    load_yearly_flood_deaths,
    load_yearly_pandemic_deaths,
    load_yearly_volcanoes,
    load_yearly_cyclone_deaths,
)


def z_score(s):
    s = s.astype(float)
    mean = np.nanmean(s.values)
    std = np.nanstd(s.values)
    if std == 0 or np.isnan(std):
        return s * np.nan
    return (s - mean) / std


def find_contractions(rolling_z, threshold=0.25, min_duration=3):
    """Identify continuous runs where rolling_z > threshold."""
    contractions = []
    in_run = False
    run_start = None
    yrs = sorted(rolling_z.dropna().index)
    for i, yr in enumerate(yrs):
        val = rolling_z.loc[yr]
        is_high = val > threshold
        if is_high and not in_run:
            in_run = True
            run_start = yr
        elif (not is_high or i == len(yrs) - 1) and in_run:
            run_end = yr - 1 if not is_high else yr
            if run_end - run_start + 1 >= min_duration:
                sub = rolling_z.loc[run_start:run_end]
                contractions.append({
                    "start": int(run_start),
                    "end": int(run_end),
                    "duration": int(run_end - run_start + 1),
                    "peak_z": float(sub.max()),
                    "peak_year": int(sub.idxmax()),
                    "area_above_baseline": float((sub - threshold).clip(lower=0).sum()),
                })
            in_run = False
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
    ap.add_argument("--threshold", type=float, default=0.25)
    ap.add_argument("--rolling", type=int, default=5)
    ap.add_argument("--min-duration", type=int, default=3)
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    indicators = [
        ("M>=7 quakes",
            load_yearly_quakes_m7(args.eq_db_1900, 1900, 2025)),
        ("M>=8 quakes",
            load_yearly_quakes_m8(args.eq_db_1900, 1900, 2025)),
        ("VEI>=5 eruptions",
            load_yearly_volcanoes(args.volcanoes_csv, 1900, 2025, vei_min=5)),
        ("X1+ flares",
            load_yearly_flares_x1(args.flares_csv, 1976, 2025)),
        ("War deaths log10",
            np.log10(load_yearly_war_deaths_active(args.wars_csv, 1900, 2025) + 1)),
        ("Famine deaths log10",
            np.log10(load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, 2025) + 1)),
        ("Pandemic deaths log10",
            np.log10(load_yearly_pandemic_deaths(args.pandemics_csv, 1900, 2025) + 1)),
        ("Flood deaths log10",
            np.log10(load_yearly_flood_deaths(args.floods_csv, 1985, 2025) + 1)),
        ("Cyclone deaths log10",
            np.log10(load_yearly_cyclone_deaths(args.cyclones_csv, 1950, 2025) + 1)),
    ]

    common_years = np.arange(1900, 2026)
    Z = np.full((len(indicators), len(common_years)), np.nan)
    for i, (name, series) in enumerate(indicators):
        z = z_score(series)
        for j, yr in enumerate(common_years):
            if yr in z.index:
                Z[i, j] = z.loc[yr]
    consensus = np.nanmean(Z, axis=0)
    consensus_series = pd.Series(consensus, index=common_years)
    rolling = consensus_series.rolling(args.rolling, center=True,
                                          min_periods=max(2, args.rolling // 2)).mean()

    contractions = find_contractions(rolling,
                                        threshold=args.threshold,
                                        min_duration=args.min_duration)

    print(f"Detected {len(contractions)} contraction periods "
            f"(rolling {args.rolling}-yr mean > {args.threshold}, "
            f"duration >= {args.min_duration} yr):\n")
    print(f"  {'#':>2}  {'years':<14} {'dur':>4} {'peak_z':>7} {'peak_yr':>8} {'area':>6}")
    print("  " + "-" * 55)
    for i, c in enumerate(contractions, start=1):
        print(f"  {i:>2}  {c['start']}-{c['end']:<8} {c['duration']:>4} "
                f"{c['peak_z']:>7.3f} {c['peak_year']:>8} {c['area_above_baseline']:>6.2f}")

    # Tests
    if len(contractions) >= 3:
        idx = np.arange(len(contractions))
        peaks = np.array([c["peak_z"] for c in contractions])
        durations = np.array([c["duration"] for c in contractions])
        areas = np.array([c["area_above_baseline"] for c in contractions])

        rng = np.random.default_rng(42)
        def slope_ci(y):
            y = np.asarray(y, dtype=float)
            x = np.arange(len(y))
            slope_pt, _ = np.polyfit(x, y, 1)
            boots = []
            for _ in range(2000):
                pick = rng.integers(0, len(y), len(y))
                if len(set(pick)) < 2:
                    continue
                s, _ = np.polyfit(x[pick], y[pick], 1)
                boots.append(s)
            lo, hi = np.percentile(boots, [2.5, 97.5])
            return slope_pt, lo, hi

        ps, pl, ph = slope_ci(peaks)
        ds, dl, dh = slope_ci(durations)
        as_, al, ah = slope_ci(areas)

        print(f"\nIntensification tests (n_contractions = {len(contractions)}):")
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
              label="Yearly consensus z")
    ax.plot(rolling.index, rolling.values, color="#aa3322", linewidth=2.2,
              label=f"{args.rolling}-yr centered rolling mean")
    ax.axhline(0, color="black", linewidth=0.7)
    ax.axhline(args.threshold, color="grey", linewidth=0.8, linestyle="--",
                  label=f"contraction threshold = {args.threshold}")
    for c in contractions:
        ax.axvspan(c["start"], c["end"], color="#aa3322", alpha=0.18)
        ax.annotate(f"#{contractions.index(c)+1}\npeak {c['peak_z']:.2f}\n({c['peak_year']})",
                       ((c["start"] + c["end"]) / 2, c["peak_z"] + 0.12),
                       ha="center", fontsize=8.5, alpha=0.9)
    ax.set_ylabel("Consensus z (mean across indicators)")
    ax.set_xlabel("Year")
    ax.set_xlim(common_years[0], common_years[-1])
    ax.set_title("Contraction periods: continuous stretches where many indicators run hot together",
                  fontsize=12)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="y", alpha=0.3)

    # Bottom: peak intensity bar chart per contraction
    ax = axes[1]
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
