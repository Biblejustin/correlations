"""
Israel x {global M>=7 quakes, Levant M>=4 quakes, X1+ flares} event-window tests.

For each date-precise modern Israel event (founding, wars, treaties), test
whether M>=7 quakes (anywhere), Levant M>=4 quakes (within ~500km of
Jerusalem), or X1+ flares occur within +/- N days of the event at a rate
above chance.
"""
import argparse
import json
from pathlib import Path

import pandas as pd
from scipy import stats

from correlate_events import (
    load_modern_quakes_dates,
    load_levant_quakes,
    load_flare_dates,
    load_israel_dates,
    event_window_test,
)


def run_topic(label, israel_events, target_dates, all_dates):
    print(f"\n--- {label} ---")
    print(f"  Israel events in window: {len(israel_events)}")
    print(f"  Target events in window: {len(target_dates)}")
    print("  window | observed | expected | ratio | binom p")
    print("  " + "-" * 55)
    for w in (7, 14, 30, 60, 90, 180):
        r = event_window_test(israel_events, target_dates, w, all_dates)
        print(f"  ±{w:3d}d  | {r['observed_in_window']:5d}    | "
              f"{r['expected']:7.2f}  | {r['ratio']:.3f}x | p={r['p_two_sided']:.3f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eq-db-modern", default="../earthquakes/quakes.sqlite")
    ap.add_argument("--flares-csv", default="data/flares_xclass.csv")
    ap.add_argument("--israel-json", default="data/israel_dates.json")
    args = ap.parse_args()

    israel = load_israel_dates(args.israel_json)
    # Modern date-precise events only (skip ancient_events for stats)
    israel_dates = [e["date"] for e in israel["events"] if "date" in e]
    israel_dates = pd.to_datetime(israel_dates).normalize().tolist()

    print("=" * 80)
    print("ISRAEL EVENTS × {global M>=7, Levant M>=4, X1+ flares}")
    print("=" * 80)
    print(f"Israel events tested: {len(israel_dates)}")

    # Build the all-dates universe (1965-01-01 .. 2025-12-31) — modern quakes catalog span
    all_dates = set(pd.date_range("1965-01-01", "2025-12-31", freq="D"))
    israel_in = [d for d in israel_dates if d in all_dates]
    print(f"Israel events in 1965-2025 window: {len(israel_in)}")

    # Global M>=7
    q_global = load_modern_quakes_dates(args.eq_db_modern, mag_min=7.0)
    q_global = q_global[q_global["date"].dt.year.between(1965, 2025)]
    run_topic("Israel events × Global M>=7", israel_in,
              q_global["date"].tolist(), all_dates)

    # Levant M>=4 within 500km of Jerusalem
    q_lev = load_levant_quakes(args.eq_db_modern)
    q_lev = q_lev[q_lev["date"].dt.year.between(1965, 2025)]
    print(f"\nLevant M>=4 events: {len(q_lev)}")
    run_topic("Israel events × Levant M>=4", israel_in,
              q_lev["date"].tolist(), all_dates)

    # X1+ flares
    fl = load_flare_dates(args.flares_csv)
    fl = fl[fl["date"].dt.year.between(1976, 2025)]
    # restrict all_dates to flare span for fair test
    flare_dates_universe = set(pd.date_range("1976-01-01", "2025-12-31", freq="D"))
    israel_in_flares = [d for d in israel_dates if d in flare_dates_universe]
    print(f"\nIsrael events in 1976-2025 window: {len(israel_in_flares)}")
    print(f"X1+ flares: {len(fl)}")
    run_topic("Israel events × X1+ flares", israel_in_flares,
              fl["date"].tolist(), flare_dates_universe)


if __name__ == "__main__":
    main()
