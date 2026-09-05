"""Refresh labels and analytic windows must exclude retained legacy rows."""
from contextlib import closing, redirect_stdout
import datetime as dt
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import correlate_events as loaders
import refresh_report as report


def millis(year):
    return int(dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


class RefreshReportScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'correlations'
        self.root.mkdir()
        (self.root.parent / 'earthquakes').mkdir()
        self.modern = self.root.parent / 'earthquakes/quakes.sqlite'
        self.historical = self.root.parent / 'earthquakes/quakes_1900.sqlite'

    def database(self, path, rows):
        with closing(sqlite3.connect(path)) as conn:
            conn.execute('CREATE TABLE quakes (id TEXT PRIMARY KEY,time_ms INTEGER,mag REAL)')
            conn.executemany('INSERT INTO quakes VALUES (?,?,?)', [(str(i), t, m) for i, (t, m) in enumerate(rows)])
            conn.commit()

    def test_report_counts_enforce_date_magnitude_and_current_cutoff(self):
        self.database(self.modern, [(millis(1900), 8.), (millis(1965)-1, 8.),
                                    (millis(1965), 4.), (millis(2000), 3.38),
                                    (millis(2001), 6.5), (millis(2100), 8.)])
        self.database(self.historical, [(millis(1900)-1, 8.), (millis(1900), 6.5),
                                        (millis(2000), 6.49), (millis(2001), 7.), (millis(2100), 8.)])
        before = {path: path.read_bytes() for path in (self.modern, self.historical)}
        counts = report.collect_counts(self.root, dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
        self.assertEqual(counts['usgs_m4_modern'], 2)
        self.assertEqual(counts['usgs_m65_1900'], 2)
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_significant_legacy_source_mix_is_not_labeled_live_ngdc(self):
        with closing(sqlite3.connect(self.modern)) as conn:
            conn.execute('CREATE TABLE significant_quakes (source TEXT)')
            conn.executemany('INSERT INTO significant_quakes VALUES (?)', [('local_recent',), ('noaa_mirror_2017',)] )
            conn.commit()
        status = report.significant_source_status(self.modern)
        self.assertEqual(status['status'], 'unrecorded')
        self.assertTrue(status['mixed_sources'])
        self.assertEqual(status['sources'], {'local_recent': 1, 'noaa_mirror_2017': 1})
        self.assertNotIn('NGDC', report.LABELS['significant_quakes'])

    def test_recorded_failure_status_does_not_overwrite_actual_row_source(self):
        with closing(sqlite3.connect(self.modern)) as conn:
            conn.execute('CREATE TABLE significant_quakes (source TEXT)')
            conn.execute("INSERT INTO significant_quakes VALUES ('noaa_mirror_2017')")
            conn.execute('CREATE TABLE significant_refresh_status (singleton INTEGER,checked_at TEXT,status TEXT,source TEXT,detail TEXT)')
            conn.execute("INSERT INTO significant_refresh_status VALUES (1,'2026-09-05','retained_stale','ngdc','timeout')")
            conn.commit()
        status = report.significant_source_status(self.modern)
        self.assertEqual(status['status'], 'retained_stale')
        self.assertEqual(status['refresh_source'], 'ngdc')
        self.assertEqual(status['sources'], {'noaa_mirror_2017': 1})

    def test_query_future_upper_bound_is_separate_from_observed_event_years(self):
        with closing(sqlite3.connect(self.modern)) as conn:
            conn.execute('CREATE TABLE significant_quakes (source TEXT,year INTEGER)')
            conn.executemany('INSERT INTO significant_quakes VALUES (?,?)', [('ngdc', 1900), ('ngdc', 2026)])
            conn.execute('CREATE TABLE significant_refresh_status (singleton INTEGER,checked_at TEXT,status TEXT,source TEXT,detail TEXT,start_year INTEGER,end_year INTEGER)')
            conn.execute("INSERT INTO significant_refresh_status VALUES (1,'2026-09-05','fresh','ngdc','complete query',1900,2099)")
            conn.commit()
        status = report.significant_source_status(self.modern)
        self.assertEqual(status['query_year_bounds'], {'start': 1900, 'end': 2099})
        self.assertEqual(status['observed_row_years'], {'first': 1900, 'last': 2026})
        self.assertNotIn('complete_through_year', status)

    def test_analytics_ignore_rows_outside_requested_year_or_magnitude(self):
        self.database(self.historical, [(millis(1900), 8.), (millis(2000), 7.9),
                                        (millis(2000), 8.), (millis(2002), 8.), (millis(2100), 8.)])
        counts = loaders.load_yearly_quakes_m8(str(self.historical), 2000, 2001,
                                               coverage=dict(start_year=1900, end_year=2025, complete_through_year=2025))
        self.assertEqual(counts.to_dict(), {2000: 1., 2001: 0.})

    def test_unavailable_database_is_not_created_by_reporting(self):
        self.assertIsNone(report.count_sqlite(self.modern, 'quakes'))
        self.assertEqual(report.significant_source_status(self.modern)['status'], 'unavailable')
        self.assertFalse(self.modern.exists())

    def test_legacy_unscoped_snapshot_resets_comparison_without_claiming_event_loss(self):
        snapshot = self.root / 'snapshot.json'
        snapshot.write_text(json.dumps(dict(when='2026-09-01T00:00:00+00:00', counts={'usgs_m4_modern': 999})))
        before = snapshot.read_bytes()
        output = io.StringIO()
        with patch.object(report, 'SNAPSHOT', snapshot), patch('sys.argv', ['refresh_report.py', '--dry-run']), \
             patch.object(report, 'collect_counts', return_value={'usgs_m4_modern': 2}), \
             patch.object(report, 'collect_fingerprints', return_value={}), \
             patch.object(report, 'significant_source_status', return_value=dict(status='unrecorded', sources={}, mixed_sources=False)), \
             patch.object(report, 'close_calls', return_value=[]), redirect_stdout(output):
            report.main()
        self.assertIn('comparison baseline reset', output.getvalue())
        self.assertIn('| USGS M≥4 (1965+) | — | 2 | new |', output.getvalue())
        self.assertNotIn('-997', output.getvalue())
        self.assertEqual(snapshot.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
