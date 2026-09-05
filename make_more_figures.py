"""Descriptive historical-event figures; observed coverage, no inferred significance."""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from correlate_events import (
    load_flare_dates, load_israel_dates, load_levant_quakes, load_modern_quakes_dates,
    load_yearly_famines, load_yearly_famine_deaths_active, load_yearly_flares_x1,
    load_yearly_quakes_m7, load_yearly_wars, load_yearly_war_deaths_active,
)
from detection_regimes import REGIMES, piecewise_detrend
from statistical_helpers import contiguous_overlap, last_complete_year
from make_figures import exposed_calendar_days, descriptive_window_ratios, ratio_upper


def flare_dates(args):
    frame = load_flare_dates(args.flares_csv)
    magnitude = pd.to_numeric(frame["class"].astype(str).str.extract(r"^X([0-9.]+)")[0], errors="coerce")
    return frame.loc[magnitude >= 1, "date"].dt.normalize().tolist()


def israel_windows(args, out):
    source = load_israel_dates(args.israel_json)
    dates = pd.to_datetime([e["date"] for e in source["events"] if "date" in e]).normalize().tolist()
    quake_scope = load_yearly_quakes_m7(args.eq_db_modern, 1965, args.year_hi)
    flare_scope = load_yearly_flares_x1(args.flares_csv, 1976, args.year_hi)
    global_dates = load_modern_quakes_dates(args.eq_db_modern, mag_min=7).date.tolist()
    levant_dates = load_levant_quakes(args.eq_db_modern).date.tolist()
    widths = [7, 14, 30, 60, 90, 180]
    specs = [("Recorded global M≥7 quakes", global_dates, exposed_calendar_days(quake_scope), "#3355aa"),
             ("Recorded Levant M≥4 quakes, radius≈500km", levant_dates, exposed_calendar_days(quake_scope), "#aa6633"),
             ("Listed X1+ flares", flare_dates(args), exposed_calendar_days(flare_scope), "#ee8833")]
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)
    frames = []
    for ax, (label, targets, exposure, color) in zip(axes, specs):
        result = descriptive_window_ratios(dates, targets, exposure, widths, modes=("centered",))
        result.insert(0, "target", label); frames.append(result)
        x = np.arange(len(widths)); ax.bar(x, result.ratio, color=color, alpha=.75, edgecolor="black")
        ax.axhline(1, color="black", linewidth=1)
        for i, ratio in enumerate(result.ratio):
            if not np.isfinite(ratio):
                ax.text(i, .05, "N/A", ha="center", fontsize=8)
        ax.set_xticks(x, [f"±{w}d" for w in widths])
        ax.set_title(label + f"\n{int(result.n_event_days.iloc[0])} selected event days; {int(result.n_targets.iloc[0])} target records", fontsize=9)
    combined = pd.concat(frames, ignore_index=True)
    for ax in axes:
        ax.set_ylim(0, ratio_upper(combined.ratio, floor=2))
    axes[0].set_ylabel("Observed / uniform-exposure baseline")
    fig.suptitle("Selected Israel event dates: descriptive window ratios; no significance or fulfillment inference", fontsize=11)
    fig.tight_layout(); fig.savefig(out / "08_israel_window_ratios.png", dpi=120); plt.close(fig)
    combined.to_csv(out / "08_israel_window_ratios.csv", index=False)


def flares_quakes_windows(args, out):
    quake_scope = load_yearly_quakes_m7(args.eq_db_modern, 1976, args.year_hi)
    flare_scope = load_yearly_flares_x1(args.flares_csv, 1976, args.year_hi)
    exposure = exposed_calendar_days(quake_scope, flare_scope)
    quakes = load_modern_quakes_dates(args.eq_db_modern, mag_min=7).date.tolist()
    widths = [0, 1, 3, 7, 14, 30]
    result = descriptive_window_ratios(flare_dates(args), quakes, exposure, widths)
    result.to_csv(out / "09_flares_quakes_windows.csv", index=False)
    fig, ax = plt.subplots(figsize=(10, 5.5)); x = np.arange(len(widths)); bar_width = .4
    for offset, mode, color in [(-bar_width/2, "centered", "#cc4422"), (bar_width/2, "after", "#ee8833")]:
        values = result.loc[result["mode"] == mode, "ratio"].to_numpy()
        ax.bar(x + offset, values, width=bar_width, color=color, alpha=.85, label=mode)
        for i, value in enumerate(values):
            if not np.isfinite(value):
                ax.text(i + offset, .03, "N/A", rotation=90, ha="center", fontsize=8)
    ax.axhline(1, color="black", linewidth=1)
    ax.set_xticks(x, [f"{w}d" for w in widths]); ax.set_xlabel("Window width around listed X1+ flares")
    ax.set_ylabel("Observed M≥7 count / uniform-exposure baseline")
    ax.set_title("Flare-window earthquake ratios\nDescriptive comparisons; clustering, selection, and uncertainty not calibrated here")
    ax.set_ylim(0, ratio_upper(result.ratio)); ax.legend()
    fig.tight_layout(); fig.savefig(out / "09_flares_quakes_windows.png", dpi=120); plt.close(fig)


def scatter_panel(ax, raw_x, raw_y, regime_x, regime_y, xlabel, ylabel, title, color):
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel); ax.set_title(title)
    try:
        frame = contiguous_overlap({"x": raw_x, "y": raw_y}, min_years=8)
    except ValueError as exc:
        ax.text(.5, .5, "Unavailable: insufficient observed overlap", ha="center", transform=ax.transAxes)
        return dict(title=title, r=None, n=0, status=str(exc))
    x = piecewise_detrend(frame.x, REGIMES.get(regime_x, []))
    y = piecewise_detrend(frame.y, REGIMES.get(regime_y, []))
    if min(x.std(), y.std()) <= 1e-12:
        ax.text(.5, .5, "Unavailable: constant residual series", ha="center", transform=ax.transAxes)
        return dict(title=title, r=None, n=len(frame), status="constant residual series")
    r = float(np.corrcoef(x, y)[0, 1])
    slope, intercept = np.polyfit(x, y, 1)
    xs = np.linspace(x.min(), x.max(), 50)
    ax.scatter(x, y, s=50, alpha=.7, color=color, edgecolor="black")
    ax.plot(xs, slope * xs + intercept, color="black", linestyle="--", alpha=.6,
            label=f"Descriptive OLS, r={r:+.3f}; n={len(frame)}\nObserved {int(frame.index.min())}–{int(frame.index.max())}")
    ax.axhline(0, color="gray", linewidth=.5); ax.axvline(0, color="gray", linewidth=.5); ax.legend(fontsize=9)
    return dict(title=title, r=r, n=len(frame), start_year=int(frame.index.min()),
                end_year=int(frame.index.max()), status="descriptive; no p-value or significance claim")


def wars_famines_scatter(args, out):
    wars = load_yearly_wars(args.wars_csv, 1976, args.year_hi)
    famines = load_yearly_famines(args.famines_csv, 1976, args.year_hi)
    flares = load_yearly_flares_x1(args.flares_csv, 1976, args.year_hi)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    rows = []
    for ax, series, regime, label, color in [(axes[0], wars, "wars_global", "Listed war onsets/year", "#aa3322"),
                                           (axes[1], famines, "famines", "Listed famine onsets/year", "#995533")]:
        rows.append(scatter_panel(ax, flares, series, "flares_x", regime,
                                  "Listed X1+ flares/year (regime residual)", label + " (regime residual)",
                                  label + " vs flare counts", color))
    fig.suptitle("Observed annual catalogue relationships after regime detrending; descriptive fits", fontsize=11)
    fig.tight_layout(); fig.savefig(out / "10_wars_famines_scatter.png", dpi=120); plt.close(fig)
    (out / "10_wars_famines_scatter.json").write_text(json.dumps(rows, indent=2))


def deaths_overview(args, out):
    """Mortality allocation proxies for selected historical events (log10)."""
    wars_log = load_yearly_war_deaths_active(args.wars_csv, 1500, args.year_hi, log10_transform=True)
    fam_log = load_yearly_famine_deaths_active(args.famines_csv, 1500, args.year_hi, log10_transform=True)
    m7 = load_yearly_quakes_m7(args.eq_db_1900, 1900, args.year_hi)
    xf = load_yearly_flares_x1(args.flares_csv, 1976, args.year_hi)

    fig, axes = plt.subplots(4, 1, figsize=(13, 12), sharex=True)
    ax = axes[0]
    ax.fill_between(wars_log.index, 0, wars_log.values, color="#aa3322", alpha=0.65)
    ax.set_ylabel("log10(war deaths/yr + 1)", fontsize=10)
    ax.set_title("Historical mortality allocation proxies and recorded event counts", fontsize=12)
    # annotate WWII, WWI, Taiping, 30 Years
    for yr, label in [(1942, "WWII"), (1916, "WWI"), (1857, "Taiping"), (1633, "30 Years")]:
        if yr in wars_log.index and wars_log.loc[yr] > 5:
            ax.annotate(label, (yr, wars_log.loc[yr]),
                        xytext=(0, 5), textcoords="offset points",
                        ha="center", fontsize=9, alpha=0.8)
    ax.set_xlim(1500, args.year_hi)

    ax = axes[1]
    ax.fill_between(fam_log.index, 0, fam_log.values, color="#995533", alpha=0.65)
    ax.set_ylabel("log10(famine deaths/yr + 1)", fontsize=10)
    for yr, label in [(1960, "Gt Chinese"), (1877, "Gt Famine"), (1942, "Bengal"), (1932, "Holodomor")]:
        if yr in fam_log.index and fam_log.loc[yr] > 5:
            ax.annotate(label, (yr, fam_log.loc[yr]),
                        xytext=(0, 5), textcoords="offset points",
                        ha="center", fontsize=9, alpha=0.8)
    ax.set_xlim(1500, args.year_hi)

    ax = axes[2]
    ax.bar(m7.index, m7.values, color="#3355aa", alpha=0.75, width=1.0)
    ax.set_ylabel("M>=7 quakes / yr", fontsize=10)
    ax.set_xlim(1500, args.year_hi)
    ax.axvspan(1900, args.year_hi, color="lightblue", alpha=0.15)

    ax = axes[3]
    ax.bar(xf.index, xf.values, color="#ee8833", alpha=0.85, width=1.0)
    ax.set_ylabel("X1+ flares / yr", fontsize=10)
    ax.set_xlabel("Year")
    ax.set_xlim(1500, args.year_hi)
    ax.axvspan(1976, args.year_hi, color="lightblue", alpha=0.15)

    plt.tight_layout()
    plt.savefig(out / "11_deaths_overview.png", dpi=120)
    plt.close()
    print(f"Wrote {out/'11_deaths_overview.png'}")


def deaths_vs_flares_scatter(args, out):
    wars = load_yearly_war_deaths_active(args.wars_csv, 1976, args.year_hi, log10_transform=True)
    famines = load_yearly_famine_deaths_active(args.famines_csv, 1976, args.year_hi, log10_transform=True)
    flares = load_yearly_flares_x1(args.flares_csv, 1976, args.year_hi)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5)); rows = []
    for ax, series, regime, label, color in [(axes[0], wars, "wars_global", "War mortality allocation", "#aa3322"),
                                           (axes[1], famines, "famines", "Famine mortality allocation", "#995533")]:
        rows.append(scatter_panel(ax, flares, series, "flares_x", regime,
                                  "Listed X1+ flares/year (regime residual)", "log10(allocation+1) (regime residual)",
                                  label + " vs flare counts", color))
    fig.suptitle("Historical event-mortality allocations: descriptive observed-overlap fits, no significance claim", fontsize=11)
    fig.tight_layout(); fig.savefig(out / "12_deaths_vs_flares_scatter.png", dpi=120); plt.close(fig)
    (out / "12_deaths_vs_flares_scatter.json").write_text(json.dumps(rows, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eq-db-modern", default="../earthquakes/quakes.sqlite")
    ap.add_argument("--eq-db-1900", default="../earthquakes/quakes_1900.sqlite")
    ap.add_argument("--flares-csv", default="data/flares_xclass.csv")
    ap.add_argument("--wars-csv", default="data/wars.csv")
    ap.add_argument("--famines-csv", default="data/famines.csv")
    ap.add_argument("--israel-json", default="data/israel_dates.json")
    ap.add_argument("--year-hi", type=int, default=last_complete_year())
    ap.add_argument("--out", default="figures")
    args = ap.parse_args(); args.year_hi = min(args.year_hi, last_complete_year())
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    israel_windows(args, out); flares_quakes_windows(args, out); wars_famines_scatter(args, out)
    deaths_overview(args, out); deaths_vs_flares_scatter(args, out)
    print("Wrote figures08–12 and descriptive CSV/JSON diagnostics")


if __name__ == "__main__":
    main()
