"""
Delta report for a data refresh.

Compares current catalog counts against the snapshot committed by the last
run (data/catalog_counts.json), prints a markdown delta table suitable for
a commit message, and appends a "close calls" digest: global M6.0-6.4
earthquakes since the previous run. Those fall below our M>=6.5
detection-clean band, so they never move the statistics, but they're
exactly the events people hear about on the news (the June 2026 Italy M6.2
was one) and should be surfaced rather than silently excluded.

Usage:
  python refresh_report.py            # print report, update the snapshot
  python refresh_report.py --dry-run  # print report, leave snapshot alone

The snapshot file is committed to git, so deltas survive machine changes
and the count history is versioned.
"""
import argparse
import datetime
import json
import sqlite3
from pathlib import Path

import pandas as pd
from source_tracking import collect_fingerprints, changed_groups

SNAPSHOT = Path("data/catalog_counts.json")


def count_csv(path: str) -> int | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return len(pd.read_csv(p, low_memory=False))
    except Exception:
        return None


def count_sqlite(path: str, table: str, where: str = "") -> int | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        q = f"SELECT COUNT(*) FROM {table}" + (f" WHERE {where}" if where else "")
        return sqlite3.connect(p).execute(q).fetchone()[0]
    except Exception:
        return None


def collect_counts() -> dict:
    return {
        "usgs_m4_modern": count_sqlite("../earthquakes/quakes.sqlite", "quakes"),
        "usgs_m65_1900": count_sqlite("../earthquakes/quakes_1900.sqlite", "quakes"),
        "significant_quakes": count_sqlite("../earthquakes/quakes.sqlite",
                                             "significant_quakes"),
        "silso_days": count_sqlite("../spaceweather/spaceweather.sqlite", "silso_daily"),
        "gfz_days": count_sqlite("../spaceweather/spaceweather.sqlite", "gfz_daily"),
        "ngdc_quakes": count_csv("data/noaa_significant_earthquakes.csv"),
        "ngdc_volcanoes": count_csv("data/noaa_volcanic_events.csv"),
        "ucdp_conflict_years": count_csv("data/ucdp_prio_conflicts.csv"),
        "terrorism_years": count_csv("data/terrorism.csv"),
    }


LABELS = {
    "usgs_m4_modern": "USGS M≥4 (1965+)",
    "usgs_m65_1900": "USGS M≥6.5 (1900+)",
    "significant_quakes": "NGDC significant (fatalities table)",
    "silso_days": "SILSO sunspot days",
    "gfz_days": "GFZ Kp/F10.7 days",
    "ngdc_quakes": "NGDC significant quakes CSV",
    "ngdc_volcanoes": "NGDC volcanic events CSV",
    "ucdp_conflict_years": "UCDP/PRIO conflict-years",
    "terrorism_years": "OWID terrorism year-rows",
}


def close_calls(since_iso: str | None) -> list[str]:
    """Global M6.0-6.49 events since the last run (near the M>=6.5 band)."""
    db = Path("../earthquakes/quakes.sqlite")
    if not db.exists():
        return []
    if since_iso:
        since_ms = int(datetime.datetime.fromisoformat(since_iso)
                        .timestamp() * 1000)
    else:
        since_ms = int((datetime.datetime.now(datetime.timezone.utc)
                         - datetime.timedelta(days=14)).timestamp() * 1000)
    rows = sqlite3.connect(db).execute(
        "SELECT time_ms, mag, place FROM quakes "
        "WHERE mag >= 6.0 AND mag < 6.5 AND time_ms > ? ORDER BY time_ms",
        (since_ms,)).fetchall()
    out = []
    for t, m, place in rows:
        d = datetime.datetime.fromtimestamp(t / 1000, datetime.timezone.utc)
        out.append(f"M{m:.1f}  {d:%Y-%m-%d}  {place}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--flags-file", default=None,
                     help="write shell-sourceable change flags here "
                          "(ANY_CHANGE / EQ_CHANGED / SW_CHANGED, 0 or 1)")
    args = ap.parse_args()

    prev = {}
    if SNAPSHOT.exists():
        prev = json.loads(SNAPSHOT.read_text())
    prev_counts = prev.get("counts", {})
    prev_when = prev.get("when")

    now_counts = collect_counts()
    fingerprints = collect_fingerprints()
    content_changed, eq_content_changed, sw_content_changed = changed_groups(
        prev.get("fingerprints", {}), fingerprints)
    today = datetime.date.today().isoformat()

    print(f"Data refresh {today}" + (f" (previous: {prev_when[:10]})" if prev_when else ""))
    print()
    print("| Catalog | Previous | Current | Δ |")
    print("|---|---|---|---|")
    any_change = False
    for key, label in LABELS.items():
        cur = now_counts.get(key)
        old = prev_counts.get(key)
        if cur is None:
            row_cur, delta = "n/a", ""
        else:
            row_cur = f"{cur:,}"
            if old is None:
                delta = "new"
            else:
                d = cur - old
                delta = f"{d:+,}" if d else "0"
                if d:
                    any_change = True
        print(f"| {label} | {old:,} | {row_cur} | {delta} |"
              if isinstance(old, int) else
              f"| {label} | — | {row_cur} | {delta} |")
    any_change = any_change or content_changed
    if content_changed:
        print("\nSource content changed (including same-row-count revisions).")
    if not any_change and prev_counts:
        print()
        print("No catalog changed since the previous run.")

    calls = close_calls(prev_when)
    if calls:
        print()
        print(f"Close calls (global M6.0–6.4, below the M≥6.5 band, "
              f"since {prev_when[:10] if prev_when else 'two weeks ago'}):")
        for c in calls:
            print(f"  {c}")

    def _delta(key):
        cur, old = now_counts.get(key), prev_counts.get(key)
        return (cur is not None and old is not None and cur != old) or \
               (cur is not None and old is None)

    eq_changed = eq_content_changed or any(_delta(k) for k in
                      ("usgs_m4_modern", "usgs_m65_1900", "significant_quakes"))
    sw_changed = sw_content_changed or any(_delta(k) for k in ("silso_days", "gfz_days"))

    if args.flags_file:
        Path(args.flags_file).write_text(
            f"ANY_CHANGE={int(any_change or not prev_counts)}\n"
            f"EQ_CHANGED={int(eq_changed)}\n"
            f"SW_CHANGED={int(sw_changed)}\n")

    # Only rewrite the snapshot when something actually changed, so a
    # no-op refresh leaves the working tree clean (nothing to commit).
    if not args.dry_run and (any_change or not prev_counts):
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps({
            "when": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "counts": now_counts,
            "fingerprints": fingerprints,
        }, indent=2) + "\n")


if __name__ == "__main__":
    main()
