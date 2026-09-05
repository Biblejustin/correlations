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
from contextlib import closing
import datetime
import json
import sqlite3
from pathlib import Path

import pandas as pd
from source_tracking import collect_fingerprints, changed_groups

SNAPSHOT = Path("data/catalog_counts.json")
COUNT_SCOPE_VERSION = 2


def count_csv(path: str) -> int | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return len(pd.read_csv(p, low_memory=False))
    except Exception:
        return None


def count_sqlite(path: str, table: str, where: str = "", params=()) -> int | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        q = f"SELECT COUNT(*) FROM {table}" + (f" WHERE {where}" if where else "")
        with closing(sqlite3.connect(p.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
            return conn.execute(q, params).fetchone()[0]
    except Exception:
        return None


def collect_counts(root='.', as_of=None) -> dict:
    root = Path(root)
    now = as_of or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Count cutoff must include a timezone')
    end_ms = int(now.timestamp() * 1000)

    def quakes(relative, year, magnitude):
        start_ms = int(datetime.datetime(year, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
        return count_sqlite(root / relative, 'quakes', 'time_ms >= ? AND time_ms <= ? AND mag >= ?',
                            (start_ms, end_ms, magnitude))

    return {
        "usgs_m4_modern": quakes("../earthquakes/quakes.sqlite", 1965, 4.),
        "usgs_m65_1900": quakes("../earthquakes/quakes_1900.sqlite", 1900, 6.5),
        "significant_quakes": count_sqlite(root / "../earthquakes/quakes.sqlite",
                                             "significant_quakes"),
        "silso_days": count_sqlite(root / "../spaceweather/spaceweather.sqlite", "silso_daily"),
        "gfz_days": count_sqlite(root / "../spaceweather/spaceweather.sqlite", "gfz_daily"),
        "ngdc_quakes": count_csv(root / "data/noaa_significant_earthquakes.csv"),
        "ngdc_volcanoes": count_csv(root / "data/noaa_volcanic_events.csv"),
        "ucdp_conflict_years": count_csv(root / "data/ucdp_prio_conflicts.csv"),
        "terrorism_years": count_csv(root / "data/terrorism.csv"),
    }


def significant_source_status(path='../earthquakes/quakes.sqlite') -> dict:
    """Read actual row provenance and last refresh status; legacy origin stays explicit."""
    path = Path(path)
    result = dict(status='unavailable', sources={}, mixed_sources=False)
    if not path.exists():
        return result
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
            conn.execute('BEGIN')
            counts = conn.execute('SELECT source,COUNT(*) FROM significant_quakes GROUP BY source').fetchall()
            sources = {}
            for source, count in counts:
                key = source or 'unknown'
                sources[key] = sources.get(key, 0) + count
            result.update(status='unrecorded', sources=sources, mixed_sources=len(sources) > 1)
            columns = {row[1] for row in conn.execute('PRAGMA table_info(significant_quakes)')}
            if 'year' in columns:
                first, last = conn.execute('SELECT MIN(year),MAX(year) FROM significant_quakes').fetchone()
                result['observed_row_years'] = dict(first=first, last=last)
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='significant_refresh_status'").fetchone():
                row = conn.execute('SELECT checked_at,status,source,detail FROM significant_refresh_status WHERE singleton=1').fetchone()
                if row:
                    result.update(checked_at=row[0], status=row[1], refresh_source=row[2], detail=row[3])
                status_columns = {row[1] for row in conn.execute('PRAGMA table_info(significant_refresh_status)')}
                if {'start_year', 'end_year'} <= status_columns:
                    scope = conn.execute('SELECT start_year,end_year FROM significant_refresh_status WHERE singleton=1').fetchone()
                    if scope:
                        result['query_year_bounds'] = dict(start=scope[0], end=scope[1])
    except sqlite3.Error as error:
        result.update(status='unavailable', detail=str(error))
    return result


LABELS = {
    "usgs_m4_modern": "USGS M≥4 (1965+)",
    "usgs_m65_1900": "USGS M≥6.5 (1900+)",
    "significant_quakes": "Significant earthquake records",
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
    with closing(sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        rows = conn.execute(
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
    prev_counts = dict(prev.get("counts", {}))
    scope_reset = bool(prev_counts) and prev.get('count_scope_version') != COUNT_SCOPE_VERSION
    if scope_reset:
        # Old snapshots counted every retained row regardless of the label.
        # Do not present a definition correction as event additions/removals.
        for key in ('usgs_m4_modern', 'usgs_m65_1900'):
            prev_counts.pop(key, None)
    prev_when = prev.get("when")

    now_counts = collect_counts()
    significant_status = significant_source_status()
    fingerprints = collect_fingerprints()
    content_changed, eq_content_changed, sw_content_changed = changed_groups(
        prev.get("fingerprints", {}), fingerprints)
    today = datetime.date.today().isoformat()

    print(f"Data refresh {today}" + (f" (previous: {prev_when[:10]})" if prev_when else ""))
    if scope_reset:
        print('Earthquake count scope corrected; comparison baseline reset for the two scoped USGS totals.')
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
    sources = ', '.join(f'{source}={count:,}' for source, count in sorted(significant_status['sources'].items())) or 'unknown'
    print(f'\nSignificant-earthquake refresh status: {significant_status["status"]}; stored row sources: {sources}.')
    query_years = significant_status.get('query_year_bounds')
    observed_years = significant_status.get('observed_row_years')
    if query_years:
        print(f'Requested query years: {query_years["start"]}–{query_years["end"]} (selection bounds, not observed coverage).')
    if observed_years:
        print(f'Stored significant-event year span: {observed_years["first"]}–{observed_years["last"]}; event dates alone do not establish complete coverage.')
    previous_status = {k: v for k, v in prev.get('significant_source_status', {}).items() if k != 'checked_at'}
    current_status = {k: v for k, v in significant_status.items() if k != 'checked_at'}
    provenance_changed = previous_status != current_status
    any_change = any_change or content_changed or scope_reset or provenance_changed
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

    eq_changed = eq_content_changed or provenance_changed or any(_delta(k) for k in
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
            "count_scope_version": COUNT_SCOPE_VERSION,
            "significant_source_status": significant_status,
            "fingerprints": fingerprints,
        }, indent=2) + "\n")


if __name__ == "__main__":
    main()
