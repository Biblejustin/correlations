"""
Additional figures for the multi-topic analyses:

  08_israel_window_ratios.png    Israel events × {global M>=7, Levant M>=4, X1+
                                 flares} window ratios, 3-panel bar chart
  09_flares_quakes_windows.png   X1+ flares × M>=7 daily-window ratios
                                 (centered + after-only)
  10_wars_famines_scatter.png    Detrended scatter for the two "interesting"
                                 results: wars vs X1+ flares, famines vs X1+
                                 flares (both 1976-2025)
"""
import argparse
import json
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from correlate_events import (
    event_window_test,
    load_flare_dates,
    load_israel_dates,
    load_levant_quakes,
    load_modern_quakes_dates,
    load_yearly_famines,
    load_yearly_famine_deaths_active,
    load_yearly_flares_x1,
    load_yearly_quakes_m7,
    load_yearly_wars,
    load_yearly_war_deaths_active,
)
from detection_regimes import REGIMES, piecewise_detrend


def israel_windows(args, out):
    israel = load_israel_dates(args.israel_json)
    israel_dates = pd.to_datetime([e["date"] for e in israel["events"] if "date" in e]).normalize().tolist()

    all_dates_mod = set(pd.date_range("1965-01-01", "2025-12-31", freq="D"))
    all_dates_flare = set(pd.date_range("1976-01-01", "2025-12-31", freq="D"))
    israel_modern = [d for d in israel_dates if d in all_dates_mod]
    israel_flare = [d for d in israel_dates if d in all_dates_flare]

    q_global = load_modern_quakes_dates(args.eq_db_modern, mag_min=7.0)
    q_global = q_global[q_global["date"].dt.year.between(1965, 2025)]
    q_lev = load_levant_quakes(args.eq_db_modern)
    q_lev = q_lev[q_lev["date"].dt.year.between(1965, 2025)]
    fl = load_flare_dates(args.flares_csv)
    fl = fl[fl["date"].dt.year.between(1976, 2025)]

    widths = [7, 14, 30, 60, 90, 180]

    def collect(events, targets, all_d):
        ratios, ps = [], []
        for w in widths:
            r = event_window_test(events, targets, w, all_d)
            ratios.append(r["ratio"] if r["ratio"] == r["ratio"] else 1.0)
            ps.append(r["p_two_sided"])
        return ratios, ps

    r_glob, p_glob = collect(israel_modern, q_global["date"].tolist(), all_dates_mod)
    r_lev, p_lev = collect(israel_modern, q_lev["date"].tolist(), all_dates_mod)
    r_fl, p_fl = collect(israel_flare, fl["date"].tolist(), all_dates_flare)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)
    titles = [
        f"Global M>=7 quakes\n(n_events={len(israel_modern)}, n_targets={len(q_global)})",
        f"Levant M>=4 quakes (<=500km of Jerusalem)\n(n_events={len(israel_modern)}, n_targets={len(q_lev)})",
        f"X1+ solar flares\n(n_events={len(israel_flare)}, n_targets={len(fl)})",
    ]
    for ax, ratios, ps, title, color in zip(
        axes, [r_glob, r_lev, r_fl], [p_glob, p_lev, p_fl], titles,
        ["#3355aa", "#aa6633", "#ee8833"],
    ):
        x = np.arange(len(widths))
        ax.bar(x, ratios, color=color, alpha=0.75, edgecolor="black")
        ax.axhline(1.0, color="black", linewidth=1.2)
        for i, (r, p) in enumerate(zip(ratios, ps)):
            ax.text(i, r + 0.04, f"p={p:.2f}", ha="center", fontsize=8)
        ax.set_xticks(x)
        ax.set_xticklabels([f"±{w}d" for w in widths])
        ax.set_title(title, fontsize=10)
        ax.set_ylim(0, max(2.0, max(ratios) * 1.3))
    axes[0].set_ylabel("Observed / chance expectation")
    plt.suptitle("Israel events × {global quakes, Levant quakes, X1+ flares} — all near 1.0×",
                 fontsize=12)
    plt.tight_layout()
    plt.savefig(out / "08_israel_window_ratios.png", dpi=120)
    plt.close()
    print(f"Wrote {out/'08_israel_window_ratios.png'}")


def flares_quakes_windows(args, out):
    fl = pd.read_csv(args.flares_csv, parse_dates=["date"])
    fl = fl[fl["date"].dt.year.between(1976, 2025)]
    flare_dates = set(fl["date"].dt.normalize())

    con = sqlite3.connect(args.eq_db_modern)
    q = pd.read_sql("SELECT time_ms, mag FROM quakes WHERE mag>=7", con)
    q["date"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    q = q[q["date"].dt.year.between(1976, 2025)]
    m7_dates = q["date"].tolist()

    all_dates = set(pd.date_range("1976-01-01", "2025-12-31", freq="D"))
    n_total = len(all_dates)
    n_m7 = len(m7_dates)

    widths = [0, 1, 3, 7, 14, 30]
    rc, ra, pc, pa = [], [], [], []
    for w in widths:
        wc = set(); wa = set()
        for d in flare_dates:
            for k in range(-w, w + 1):
                wc.add(d + pd.Timedelta(days=k))
            for k in range(0, w + 1):
                wa.add(d + pd.Timedelta(days=k))
        wc &= all_dates; wa &= all_dates
        for ws, store_r, store_p in [(wc, rc, pc), (wa, ra, pa)]:
            n_in = sum(1 for d in m7_dates if d in ws)
            exp = n_m7 * len(ws) / n_total
            store_r.append(n_in / exp if exp else 1.0)
            store_p.append(stats.binomtest(n_in, n=n_m7, p=len(ws) / n_total,
                                           alternative="greater").pvalue)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    x = np.arange(len(widths))
    w_bar = 0.4
    ax.bar(x - w_bar / 2, rc, width=w_bar, color="#cc4422", alpha=0.85, label="centered (±N days)")
    ax.bar(x + w_bar / 2, ra, width=w_bar, color="#ee8833", alpha=0.85, label="after only (flare..+N)")
    ax.axhline(1.0, color="black", linewidth=1.2)
    for i, (rcv, rav, pcv, pav) in enumerate(zip(rc, ra, pc, pa)):
        ax.text(i - w_bar / 2, rcv + 0.03, f"p={pcv:.2f}", ha="center", fontsize=7.5)
        ax.text(i + w_bar / 2, rav + 0.03, f"p={pav:.2f}", ha="center", fontsize=7.5)
    ax.set_xticks(x)
    ax.set_xticklabels([f"±{w}d" if w else "0d" for w in widths])
    ax.set_ylabel("Observed M>=7 count / chance expectation")
    ax.set_xlabel("Window around X1+ flare")
    ax.set_title(
        "X1+ flares × M>=7 quakes — ±0d ratio 1.51× and +14d-after 1.25× hint at signal\n"
        "but neither survives Bonferroni for the test grid"
    )
    ax.legend()
    ax.set_ylim(0, max(rc + ra) * 1.25)
    plt.tight_layout()
    plt.savefig(out / "09_flares_quakes_windows.png", dpi=120)
    plt.close()
    print(f"Wrote {out/'09_flares_quakes_windows.png'}")


def wars_famines_scatter(args, out):
    wars = load_yearly_wars(args.wars_csv, 1976, 2025)
    famines = load_yearly_famines(args.famines_csv, 1976, 2025)
    xf = load_yearly_flares_x1(args.flares_csv, 1976, 2025)

    overlap = wars.index.intersection(xf.index).intersection(famines.index)
    wars_d = piecewise_detrend(wars.loc[overlap].astype(float), REGIMES["wars_global"])
    famines_d = piecewise_detrend(famines.loc[overlap].astype(float), REGIMES["famines"])
    xf_d = piecewise_detrend(xf.loc[overlap].astype(float), REGIMES["flares_x"])

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

    def panel(ax, x, y, xlabel, ylabel, color):
        mask = ~(x.isna() | y.isna())
        x2, y2 = x[mask], y[mask]
        r, p = stats.pearsonr(x2, y2)
        ax.scatter(x2, y2, s=60, alpha=0.7, color=color, edgecolor="black")
        slope, intercept = np.polyfit(x2, y2, 1)
        xs = np.linspace(x2.min(), x2.max(), 50)
        ax.plot(xs, slope * xs + intercept, color="black", linestyle="--", alpha=0.6,
                label=f"OLS fit  r={r:+.3f}, p={p:.3f}")
        for yr, xv, yv in zip(x2.index, x2.values, y2.values):
            if abs(xv) > 1.0 * x2.std() or abs(yv) > 1.5 * y2.std():
                ax.annotate(str(yr), (xv, yv), fontsize=8, alpha=0.7,
                            xytext=(3, 3), textcoords="offset points")
        ax.axhline(0, color="gray", linewidth=0.5)
        ax.axvline(0, color="gray", linewidth=0.5)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.legend(fontsize=9)

    panel(axes[0], xf_d, wars_d,
          "X1+ flares per year (regime-detrended)",
          "Wars started per year (regime-detrended)",
          "#aa3322")
    axes[0].set_title("Wars × X1+ flares (detrended, 1976–2025)")
    panel(axes[1], xf_d, famines_d,
          "X1+ flares per year (regime-detrended)",
          "Famines per year (regime-detrended)",
          "#995533")
    axes[1].set_title("Famines × X1+ flares (detrended, 1976–2025)")

    plt.suptitle(
        "The two largest raw correlations — both fail Bonferroni for the 8-headline-test grid",
        fontsize=11,
    )
    plt.tight_layout()
    plt.savefig(out / "10_wars_famines_scatter.png", dpi=120)
    plt.close()
    print(f"Wrote {out/'10_wars_famines_scatter.png'}")


def deaths_overview(args, out):
    """Death-weighted yearly time series for wars and famines (log10)."""
    wars_log = load_yearly_war_deaths_active(args.wars_csv, 1500, 2025, log10_transform=True)
    fam_log = load_yearly_famine_deaths_active(args.famines_csv, 1500, 2025, log10_transform=True)
    m7 = load_yearly_quakes_m7(args.eq_db_1900, 1900, 2025)
    xf = load_yearly_flares_x1(args.flares_csv, 1976, 2025)

    fig, axes = plt.subplots(4, 1, figsize=(13, 12), sharex=True)
    ax = axes[0]
    ax.fill_between(wars_log.index, 0, wars_log.values, color="#aa3322", alpha=0.65)
    ax.set_ylabel("log10(war deaths/yr + 1)", fontsize=10)
    ax.set_title("Death-weighted yearly time series (deaths spread evenly across active years)", fontsize=12)
    # annotate WWII, WWI, Taiping, 30 Years
    for yr, label in [(1942, "WWII"), (1916, "WWI"), (1857, "Taiping"), (1633, "30 Years")]:
        if yr in wars_log.index and wars_log.loc[yr] > 5:
            ax.annotate(label, (yr, wars_log.loc[yr]),
                        xytext=(0, 5), textcoords="offset points",
                        ha="center", fontsize=9, alpha=0.8)
    ax.set_xlim(1500, 2030)

    ax = axes[1]
    ax.fill_between(fam_log.index, 0, fam_log.values, color="#995533", alpha=0.65)
    ax.set_ylabel("log10(famine deaths/yr + 1)", fontsize=10)
    for yr, label in [(1960, "Gt Chinese"), (1877, "Gt Famine"), (1942, "Bengal"), (1932, "Holodomor")]:
        if yr in fam_log.index and fam_log.loc[yr] > 5:
            ax.annotate(label, (yr, fam_log.loc[yr]),
                        xytext=(0, 5), textcoords="offset points",
                        ha="center", fontsize=9, alpha=0.8)
    ax.set_xlim(1500, 2030)

    ax = axes[2]
    ax.bar(m7.index, m7.values, color="#3355aa", alpha=0.75, width=1.0)
    ax.set_ylabel("M>=7 quakes / yr", fontsize=10)
    ax.set_xlim(1500, 2030)
    ax.axvspan(1900, 2025, color="lightblue", alpha=0.15)

    ax = axes[3]
    ax.bar(xf.index, xf.values, color="#ee8833", alpha=0.85, width=1.0)
    ax.set_ylabel("X1+ flares / yr", fontsize=10)
    ax.set_xlabel("Year")
    ax.set_xlim(1500, 2030)
    ax.axvspan(1976, 2025, color="lightblue", alpha=0.15)

    plt.tight_layout()
    plt.savefig(out / "11_deaths_overview.png", dpi=120)
    plt.close()
    print(f"Wrote {out/'11_deaths_overview.png'}")


def deaths_vs_flares_scatter(args, out):
    """Detrended death-weighted scatter vs flares — shows the collapse vs onset scatter."""
    from detection_regimes import REGIMES, piecewise_detrend
    wars_log = load_yearly_war_deaths_active(args.wars_csv, 1976, 2025, log10_transform=True)
    fam_log = load_yearly_famine_deaths_active(args.famines_csv, 1976, 2025, log10_transform=True)
    xf = load_yearly_flares_x1(args.flares_csv, 1976, 2025)

    wars_d = piecewise_detrend(wars_log, REGIMES["wars_global"])
    fam_d = piecewise_detrend(fam_log, REGIMES["famines"])
    xf_d = piecewise_detrend(xf.astype(float), REGIMES["flares_x"])

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    for ax, y, ylabel, color, title in [
        (axes[0], wars_d, "log10 war deaths (detrended)", "#aa3322",
         "War deaths (log10) × X1+ flares"),
        (axes[1], fam_d, "log10 famine deaths (detrended)", "#995533",
         "Famine deaths (log10) × X1+ flares"),
    ]:
        mask = ~(xf_d.isna() | y.isna())
        x, yv = xf_d[mask], y[mask]
        r, p = stats.pearsonr(x, yv)
        ax.scatter(x, yv, s=60, alpha=0.7, color=color, edgecolor="black")
        slope, intercept = np.polyfit(x, yv, 1)
        xs = np.linspace(x.min(), x.max(), 50)
        ax.plot(xs, slope * xs + intercept, color="black", linestyle="--", alpha=0.6,
                label=f"OLS  r={r:+.3f}, p={p:.3f}")
        ax.axhline(0, color="gray", linewidth=0.5)
        ax.axvline(0, color="gray", linewidth=0.5)
        ax.set_xlabel("X1+ flares/yr (detrended)")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.legend(fontsize=9)

    plt.suptitle(
        "When weighted by ACTUAL DEATHS (not just event counts), both marginal "
        "correlations collapse to ~0",
        fontsize=11,
    )
    plt.tight_layout()
    plt.savefig(out / "12_deaths_vs_flares_scatter.png", dpi=120)
    plt.close()
    print(f"Wrote {out/'12_deaths_vs_flares_scatter.png'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eq-db-modern", default="../earthquakes/quakes.sqlite")
    ap.add_argument("--eq-db-1900", default="../earthquakes/quakes_1900.sqlite")
    ap.add_argument("--flares-csv", default="data/flares_xclass.csv")
    ap.add_argument("--wars-csv", default="data/wars.csv")
    ap.add_argument("--famines-csv", default="data/famines.csv")
    ap.add_argument("--israel-json", default="data/israel_dates.json")
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    israel_windows(args, out)
    flares_quakes_windows(args, out)
    wars_famines_scatter(args, out)
    deaths_overview(args, out)
    deaths_vs_flares_scatter(args, out)


if __name__ == "__main__":
    main()
