"""
Solar flares X1+ vs M>=7 earthquakes — daily-window test.

Same logic as the storm-day test in analyze.py, but using individual X1+ flare
peak times rather than G3+ storm days.

Unlike Kp (which is measured at Earth and already accounts for propagation),
flares are emitted at the Sun. Light/X-rays arrive in 8 minutes, so day-of
windows are physically meaningful here in a way they weren't for Kp.
"""
import argparse
import sqlite3
from pathlib import Path

import pandas as pd
from scipy import stats


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eq-db-modern", default="../earthquakes/quakes.sqlite")
    ap.add_argument("--flares-csv", default="data/flares_xclass.csv")
    ap.add_argument("--year-lo", type=int, default=1976)
    ap.add_argument("--year-hi", type=int, default=2025)
    args = ap.parse_args()

    fl = pd.read_csv(args.flares_csv, parse_dates=["date"])
    fl = fl[fl["date"].dt.year.between(args.year_lo, args.year_hi)]
    flare_dates = set(fl["date"].dt.normalize())

    con = sqlite3.connect(args.eq_db_modern)
    q = pd.read_sql("SELECT time_ms, mag FROM quakes WHERE mag>=7", con)
    q["date"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    q = q[q["date"].dt.year.between(args.year_lo, args.year_hi)]
    m7_dates = q["date"].tolist()

    all_dates = set(pd.date_range(f"{args.year_lo}-01-01", f"{args.year_hi}-12-31", freq="D"))
    n_total = len(all_dates)
    n_fl = len(flare_dates)
    n_m7 = len(m7_dates)

    print(f"X1+ flares {args.year_lo}-{args.year_hi}: {n_fl}")
    print(f"M>=7 quakes:                {n_m7}")
    print(f"Total days:                 {n_total}")
    print()
    print("Centered window (±N days around an X1+ flare):")
    print("  window | M>=7 obs | expected | ratio | one-sided binom p")
    print("  " + "-" * 60)
    for w in (0, 1, 3, 7, 14, 30):
        near = set()
        for d in flare_dates:
            for k in range(-w, w + 1):
                near.add(d + pd.Timedelta(days=k))
        near &= all_dates
        n_in = sum(1 for d in m7_dates if d in near)
        expected = n_m7 * len(near) / n_total
        p = stats.binomtest(n_in, n=n_m7, p=len(near) / n_total,
                            alternative="greater").pvalue
        ratio = n_in / expected if expected else float("nan")
        print(f"  ±{w:2d}d   | {n_in:5d}    | {expected:7.2f}  | {ratio:.3f}x | p={p:.3f}")

    print("\nAfter-only window (flare day .. +N):")
    print("  window | M>=7 obs | expected | ratio | one-sided binom p")
    print("  " + "-" * 60)
    for w in (0, 1, 3, 7, 14, 30):
        near = set()
        for d in flare_dates:
            for k in range(0, w + 1):
                near.add(d + pd.Timedelta(days=k))
        near &= all_dates
        n_in = sum(1 for d in m7_dates if d in near)
        expected = n_m7 * len(near) / n_total
        p = stats.binomtest(n_in, n=n_m7, p=len(near) / n_total,
                            alternative="greater").pvalue
        ratio = n_in / expected if expected else float("nan")
        print(f"  +{w:2d}d   | {n_in:5d}    | {expected:7.2f}  | {ratio:.3f}x | p={p:.3f}")


if __name__ == "__main__":
    main()
