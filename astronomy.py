"""
Astronomical signs × {M>=7 quakes, wars, etc.} correlation tests.

Mt 24:29 framing: "the sun shall be darkened, and the moon shall not give her
light, and the stars shall fall from heaven." Tests whether eclipse years,
comet years, or supernova years cluster with terrestrial events.

Strong null prior — celestial mechanics is independent of terrestrial events.
"""
import argparse
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from scipy import stats

from correlate_events import (
    load_yearly_quakes_m7,
    load_astronomical_signs,
    load_yearly_astro_events,
    yearly_corr,
)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eq-db-1900", default="../earthquakes/quakes_1900.sqlite")
    ap.add_argument("--eq-db-modern", default="../earthquakes/quakes.sqlite")
    ap.add_argument("--astro-csv", default="data/astronomical_signs.csv")
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    astro_all = load_yearly_astro_events(args.astro_csv, 1900, 2025)
    eclipses = load_yearly_astro_events(args.astro_csv, 1900, 2025, types=["total_solar"])
    comets = load_yearly_astro_events(args.astro_csv, 1900, 2025, types=["comet"])
    m7 = load_yearly_quakes_m7(args.eq_db_1900, 1900, 2025)

    for label, series in [("All astro events", astro_all),
                          ("Total solar eclipses", eclipses),
                          ("Naked-eye comets", comets)]:
        print("=" * 80)
        print(f"{label.upper()} × M>=7 QUAKES (1900-2025)")
        print("=" * 80)
        r = yearly_corr(series, m7, regime_key_a="astro", regime_key_b="quakes_m7")
        print(f"  n={r['n']}, non-zero years: {(series>0).sum()}")
        print(f"  Raw Pearson r      : {r['raw_r']:+.3f}  p={r['raw_p']:.3f}")
        print(f"  Regime-detrended r : {r['det_r']:+.3f}  p={r['det_p']:.3f}")
        print()

    # Daily-window test: M>=7 quakes near total solar eclipses
    print("=" * 80)
    print("DAILY-WINDOW: M>=7 within +/- N days of total solar eclipse (1965-2025)")
    print("=" * 80)
    astro_df = load_astronomical_signs(args.astro_csv, 1900, 2025,
                                          types=["total_solar"])
    eclipse_dates = [pd.Timestamp(d).normalize() for d in astro_df["date"].dropna()
                     if 1965 <= pd.Timestamp(d).year <= 2025]
    print(f"Total solar eclipses 1965-2025 in catalog: {len(eclipse_dates)}")

    con = sqlite3.connect(args.eq_db_modern)
    q = pd.read_sql("SELECT time_ms, mag FROM quakes WHERE mag>=7", con)
    q["date"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    q = q[q["date"].dt.year.between(1965, 2025)]
    m7_dates = q["date"].tolist()
    all_dates = set(pd.date_range("1965-01-01", "2025-12-31", freq="D"))
    n_total = len(all_dates); n_m7 = len(m7_dates)

    print("\n  window | M>=7 obs | expected | ratio | one-sided binom p")
    print("  " + "-" * 60)
    for w in (0, 1, 3, 7, 30):
        win = set()
        for d in eclipse_dates:
            for k in range(-w, w + 1):
                win.add(d + pd.Timedelta(days=k))
        win &= all_dates
        n_in = sum(1 for d in m7_dates if d in win)
        expected = n_m7 * len(win) / n_total
        p = stats.binomtest(n_in, n=n_m7, p=len(win)/n_total, alternative="greater").pvalue
        ratio = n_in / expected if expected else float("nan")
        print(f"  ±{w:3d}d  | {n_in:5d}    | {expected:7.2f}  | {ratio:.3f}x | p={p:.3f}")

    fig, ax = plt.subplots(figsize=(13, 4))
    ax.bar(astro_all.index, astro_all.values, color="#553388", alpha=0.65,
           label="All astro events/yr")
    ax.bar(eclipses.index, eclipses.values, color="#aa3322", alpha=0.85, width=0.6,
           label="Total solar eclipses")
    ax.set_ylabel("Events/yr")
    ax.set_xlabel("Year")
    ax.set_title('Astronomical "signs in the heavens" (1900-2025)')
    ax.legend()
    plt.tight_layout()
    plt.savefig(out / "17_astronomy_overview.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'17_astronomy_overview.png'}")


if __name__ == "__main__":
    main()
