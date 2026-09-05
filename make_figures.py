"""Descriptive earthquake/storm figures using observed source exposure."""
import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from correlate_events import load_yearly_quakes_m7
from periodogram_extended import load_g3_days
from statistical_helpers import contiguous_overlap, last_complete_year


def exposed_calendar_days(*annual_series):
    """Calendar days in years observed by every supplied catalogue."""
    frame = pd.DataFrame({str(i): s for i, s in enumerate(annual_series)})
    years = frame.index[np.isfinite(frame.to_numpy()).all(axis=1)]
    return {d for year in years for d in pd.date_range(f"{int(year)}-01-01", f"{int(year)}-12-31")}


def descriptive_window_ratios(events, targets, exposure, widths, modes=("centered", "after")):
    """Ratios to uniform observed-day exposure, without an inferential claim."""
    exposure = set(exposure)
    events = {pd.Timestamp(d).normalize() for d in events} & exposure
    targets = [pd.Timestamp(d).normalize() for d in targets if pd.Timestamp(d).normalize() in exposure]
    rows = []
    for width in widths:
        for mode in modes:
            offsets = range(-width, width + 1) if mode == "centered" else range(width + 1)
            window = {day + pd.Timedelta(days=k) for day in events for k in offsets} & exposure
            expected = len(targets) * len(window) / len(exposure) if exposure else np.nan
            observed = sum(day in window for day in targets)
            ratio = observed / expected if np.isfinite(expected) and expected > 0 else np.nan
            rows.append(dict(window_days=width, mode=mode, ratio=ratio, observed=observed,
                             expected_uniform=expected, n_exposure_days=len(exposure),
                             n_event_days=len(events), n_targets=len(targets),
                             status="descriptive; no significance test" if np.isfinite(ratio) else "unavailable"))
    return pd.DataFrame(rows)


def ratio_upper(values, floor=1.2):
    finite = np.asarray(values, float)
    finite = finite[np.isfinite(finite)]
    return max(floor, float(finite.max()) * 1.25) if len(finite) else floor


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sw-db", default="../spaceweather/spaceweather.sqlite")
    ap.add_argument("--eq-db", default="../earthquakes/quakes.sqlite")
    ap.add_argument("--out", default="figures")
    ap.add_argument("--year-lo", type=int, default=1965)
    ap.add_argument("--year-hi", type=int, default=last_complete_year())
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    year_hi = min(args.year_hi, last_complete_year())
    with closing(sqlite3.connect(f"file:{Path(args.sw_db).resolve()}?mode=ro", uri=True)) as con:
        gfz = pd.read_sql("SELECT date_iso,kp1,kp2,kp3,kp4,kp5,kp6,kp7,kp8 FROM gfz_daily WHERE date_iso BETWEEN ? AND ?",
                          con, params=(f"{args.year_lo}-01-01", f"{year_hi}-12-31"), parse_dates=["date_iso"])
    with closing(sqlite3.connect(f"file:{Path(args.eq_db).resolve()}?mode=ro", uri=True)) as con:
        quakes = pd.read_sql("SELECT time_ms FROM quakes WHERE mag>=7", con)
    slots = gfz[[f"kp{i}" for i in range(1, 9)]]
    valid = slots.notna().all(axis=1) & (slots >= 0).all(axis=1) & (slots <= 9).all(axis=1)
    gfz = gfz.loc[valid].copy()
    gfz["peak_kp"] = slots.loc[valid].max(axis=1)
    gfz["date"] = gfz.date_iso.dt.normalize()
    quakes["date"] = pd.to_datetime(quakes.time_ms, unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    m7 = load_yearly_quakes_m7(args.eq_db, args.year_lo, year_hi)
    g3 = load_g3_days(args.sw_db, args.year_lo, year_hi)
    pd.DataFrame({"m7_quakes": m7, "g3_storm_days": g3}).to_csv(out / "01_yearly_overlay.csv", index_label="year")
    metadata = {"status": "insufficient variable contiguous overlap", "r": None, "n": 0}
    try:
        observed = contiguous_overlap({"m7": m7, "g3": g3}, min_years=8)
        if min(observed.std()) > 1e-12:
            metadata = dict(status="descriptive Pearson correlation", r=float(observed.corr().iloc[0, 1]),
                            n=len(observed), start_year=int(observed.index.min()), end_year=int(observed.index.max()))
    except ValueError:
        pass
    (out / "01_yearly_overlay.json").write_text(json.dumps(metadata, indent=2))
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.bar(m7.index, m7, color="#cc4422", alpha=.7)
    ax.set_ylabel("Recorded M≥7 earthquakes/year", color="#cc4422"); ax.set_xlabel("Year")
    twin = ax.twinx(); twin.plot(g3.index, g3, color="#3355aa", marker="o", linewidth=1.5)
    twin.set_ylabel("Observed G3+ storm days/year", color="#3355aa")
    detail = (f"Descriptive r={metadata['r']:+.3f}, n={metadata['n']} ({metadata['start_year']}–{metadata['end_year']}); no significance test"
              if metadata["r"] is not None else "Correlation unavailable: insufficient observed overlap")
    ax.set_title(f"Earthquake and geomagnetic records, {args.year_lo}–{year_hi}\n{detail}")
    fig.tight_layout(); fig.savefig(out / "01_yearly_overlay.png", dpi=120); plt.close(fig)

    # Daily comparisons use only valid eight-slot Kp days and observed quake scope.
    exposure = set(gfz.date) & exposed_calendar_days(m7)
    storms = set(gfz.loc[gfz.peak_kp >= 7, "date"])
    widths = [0, 1, 3, 7, 14, 30]
    ratios = descriptive_window_ratios(storms, quakes.date.tolist(), exposure, widths)
    ratios.to_csv(out / "02_window_ratios.csv", index=False)
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(widths)); width = .4
    for offset, mode, color in [(-width/2, "centered", "#3355aa"), (width/2, "after", "#88aacc")]:
        values = ratios.loc[ratios["mode"] == mode, "ratio"].to_numpy()
        ax.bar(x + offset, values, width=width, label=mode, color=color)
        for i, value in enumerate(values):
            if not np.isfinite(value):
                ax.text(i + offset, .03, "N/A", rotation=90, ha="center", fontsize=8)
    ax.axhline(1, color="black", linewidth=1)
    ax.set_xticks(x, [f"{w}d" for w in widths]); ax.set_xlabel("Window width")
    ax.set_ylabel("Observed M≥7 count / uniform-exposure baseline")
    ax.set_title("Storm-window earthquake ratios\nDescriptive comparison; no uncertainty or significance test")
    ax.set_ylim(0, ratio_upper(ratios.ratio)); ax.legend()
    fig.tight_layout(); fig.savefig(out / "02_window_ratios.png", dpi=120); plt.close(fig)
    print("Wrote figures01/02 and observed-exposure CSV/JSON diagnostics")


if __name__ == "__main__":
    main()
