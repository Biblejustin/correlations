"""Regression tests reproducing catalogue, precision, and allocation audit bugs."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import correlate_events as c
from catalog_coverage import apply_coverage


class LoaderIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def csv(self, rows, name='input.csv'):
        path = self.root / name
        pd.DataFrame(rows).to_csv(path, index=False)
        return str(path)

    def meta(self, start=1900, end=2025, **kwargs):
        return dict(start_year=start, end_year=end, **kwargs)

    def test_coverage_edges_gap_incomplete_and_override(self):
        s = pd.Series(0., index=range(1991, 2028))
        meta = self.meta(1992, 2026, complete_through_year=2025, gap_years=[1993])
        with patch('catalog_coverage.last_complete_year', return_value=2025):
            out = apply_coverage(s, 'unused', coverage=meta)
            self.assertTrue(out.loc[[1991, 1993, 2026, 2027]].isna().all())
            self.assertEqual(out.loc[1994], 0)
            partial = apply_coverage(s, 'unused', coverage=meta, include_incomplete=True)
            self.assertEqual(partial.loc[2026], 0)
            self.assertTrue(np.isnan(partial.loc[2027]))

    def test_sidecar_beats_catalog_explicit_beats_sidecar(self):
        path = self.root / 'volcanoes.csv'
        Path(str(path) + '.coverage.json').write_text(json.dumps(self.meta(2000, 2002)))
        s = pd.Series(0., index=range(1999, 2005))
        self.assertTrue(np.isnan(apply_coverage(s, path, 'volcanoes.csv').loc[2003]))
        out = apply_coverage(s, path, 'volcanoes.csv', coverage=self.meta(2000, 2003))
        self.assertEqual(out.loc[2003], 0)

    def test_threshold_cannot_shorten_coverage(self):
        path = self.csv([dict(year=1991, vei=6), dict(year=2022, vei=5)])
        out = c.load_yearly_volcanoes(path, 1990, 2025, vei_min=6, coverage=self.meta(1990, 2024))
        self.assertEqual(out.loc[1991], 1)
        self.assertTrue((out.loc[1992:2024] == 0).all())
        self.assertTrue(np.isnan(out.loc[2025]))
        empty = c.load_yearly_volcanoes(path, 1990, 2025, vei_min=8, coverage=self.meta(1990, 2024))
        self.assertTrue((empty.loc[1990:2024] == 0).all())

    def test_quake_threshold_uses_metadata_without_recent_m8(self):
        path = self.root / 'quakes.sqlite'
        with sqlite3.connect(path) as con:
            con.execute('CREATE TABLE quakes (time_ms INTEGER, mag REAL)')
            con.executemany('INSERT INTO quakes VALUES (?, ?)', [
                (int(pd.Timestamp('2000-01-01').timestamp()*1000), 8),
                (int(pd.Timestamp('2004-01-01').timestamp()*1000), 6.5)])
        out = c.load_yearly_quakes_m8(str(path), 1999, 2006, coverage=self.meta(2000, 2005))
        self.assertTrue(np.isnan(out.loc[1999]))
        self.assertEqual(out.loc[2005], 0)
        self.assertTrue(np.isnan(out.loc[2006]))

    def test_lifetime_allocations_invariant_to_requested_window(self):
        path = self.csv([dict(start_year=1890, end_year=1909, deaths_estimate=200,
                              displaced_estimate=600, people_affected=400, war_type='interstate')])
        names = ['load_yearly_war_deaths_active', 'load_yearly_famine_deaths_active',
                 'load_yearly_pandemic_deaths', 'load_yearly_heat_wave_deaths',
                 'load_yearly_refugee_displaced', 'load_yearly_drought_affected',
                 'load_yearly_drought_deaths']
        for name in names:
            with self.subTest(loader=name):
                loader = getattr(c, name)
                broad = loader(path, 1880, 1920, coverage=self.meta(1880, 1920))
                narrow = loader(path, 1900, 1905, coverage=self.meta(1880, 1920))
                pd.testing.assert_series_equal(broad.loc[1900:1905], narrow)
        broad = c.load_yearly_war_deaths_split(path, 'interstate', 1880, 1920, coverage=self.meta(1880, 1920))
        narrow = c.load_yearly_war_deaths_split(path, 'interstate', 1900, 1905, coverage=self.meta(1880, 1920))
        pd.testing.assert_series_equal(broad.loc[1900:1905], narrow)
        self.assertEqual(narrow.loc[1900], 10)

    def floods(self):
        return [dict(source='DFO', source_id='d1', match_group_id=1, start_date='2000-12-31',
                     end_date='2001-01-01', deaths=100, cause='rain'),
                dict(source='EM-DAT', source_id='e1', match_group_id=1, start_date='2001-01-01',
                     end_date='2001-01-02', deaths=2000, cause='rain'),
                dict(source='EM-DAT', source_id='e2', match_group_id=np.nan, start_date='2001-02-01',
                     end_date='2001-02-01', deaths=1500, cause='tsunami')]

    def test_flood_priority_precedes_all_filters(self):
        rows = self.floods()
        path = self.csv(rows)
        counts = c.load_yearly_flood_events(path, 2000, 2002, deaths_min=1000, coverage=self.meta(2000, 2002))
        dates = c.load_flood_event_dates(path, 1000, exclude_tsunami=False)
        self.assertEqual(counts.sum(), len(dates))
        self.assertEqual(counts.loc[2000], 0)
        self.assertIn(pd.Timestamp('2001-01-01'), dates)
        self.assertEqual(len(c.load_flood_event_dates(path, 1000)), 1)
        canonical = c.load_canonical_flood_events(path)
        self.assertEqual(canonical.iloc[0]['deaths_min_reported'], 100)
        self.assertEqual(canonical.iloc[0]['deaths_max_reported'], 2000)
        reverse = self.csv(rows[::-1], 'reversed.csv')
        self.assertEqual(c.load_flood_event_dates(reverse, 1000, False), dates)

    def test_flood_full_day_duration_before_slice(self):
        path = self.csv([dict(source='EM-DAT', source_id='e1', match_group_id=np.nan,
                     start_date='1999-12-31', end_date='2000-01-02', deaths=90)])
        broad = c.load_yearly_flood_deaths(path, 1999, 2001, coverage=self.meta(1999, 2001))
        narrow = c.load_yearly_flood_deaths(path, 2000, 2000, coverage=self.meta(1999, 2001))
        self.assertEqual(broad.loc[1999], 30)
        self.assertEqual(broad.loc[2000], 60)
        self.assertEqual(narrow.loc[2000], 60)
        self.assertEqual(broad.sum(), 90)

    def test_month_only_events_excluded_from_day_windows(self):
        path = self.csv([dict(year=2000, month=1, vei=6, deaths_estimate=2000)])
        self.assertEqual(c.load_volcano_dates(path), [])
        self.assertEqual(c.load_cyclone_dates(path), [])
        path = self.csv([dict(year=2000, month=1, day=3, vei=6, deaths_estimate=2000),
                         dict(year=2001, month=2, day=np.nan, vei=6, deaths_estimate=2000)])
        self.assertEqual(c.load_volcano_dates(path), [pd.Timestamp('2000-01-03')])
        self.assertEqual(c.load_cyclone_dates(path), [pd.Timestamp('2000-01-03')])

    def test_flood_parser_does_not_promote_precision(self):
        rows = self.floods()[:1]
        rows[0]['start_date'] = '2000-12'
        self.assertEqual(c.load_flood_event_dates(self.csv(rows), 0, False), [])

    def test_drought_distinct_metrics_and_missing_values(self):
        path = self.csv([dict(start_year=2000, end_year=2000, deaths_estimate=1000, people_affected=10),
                         dict(start_year=2001, end_year=2001, deaths_estimate=500, people_affected=np.nan),
                         dict(start_year=2002, end_year=2002, deaths_estimate=np.nan, people_affected=np.nan)])
        kwargs = dict(coverage=self.meta(2000, 2003))
        affected = c.load_yearly_drought_affected(path, 2000, 2003, **kwargs)
        deaths = c.load_yearly_drought_deaths(path, 2000, 2003, **kwargs)
        self.assertEqual(affected.loc[2000], 10)
        self.assertEqual(deaths.loc[2000], 1000)
        self.assertTrue(np.isnan(affected.loc[2001]))
        self.assertEqual(affected.loc[2003], 0)
        self.assertEqual(c.load_yearly_droughts(path, 2000, 2003, **kwargs).loc[2002], 1)
        self.assertEqual(c.load_yearly_droughts(path, 2000, 2003, intensity_min=100, **kwargs).sum(), 0)
        self.assertEqual(c.load_yearly_droughts(path, 2000, 2003, intensity_min=100,
                                              intensity_metric='deaths_estimate', **kwargs).sum(), 2)

    def test_invalid_flood_interval_and_unknown_mortality_stay_unknown(self):
        rows = self.floods()[:1]
        rows[0].update(start_date='2000-12-31', end_date='2000-01-01')
        out = c.load_yearly_flood_deaths(self.csv(rows), 2000, 2002, coverage=self.meta(2000, 2002))
        self.assertTrue(np.isnan(out.loc[2000]))
        rows[0].update(end_date='2001-01-01', deaths=np.nan)
        out = c.load_yearly_flood_deaths(self.csv(rows), 2000, 2002, coverage=self.meta(2000, 2002))
        self.assertTrue(out.loc[2000:2001].isna().all())
        self.assertEqual(out.loc[2002], 0)

    def test_read_only_loader_does_not_create_missing_database(self):
        path = self.root / 'absent.sqlite'
        with self.assertRaises(sqlite3.OperationalError):
            c.load_yearly_quakes_m7(str(path))
        self.assertFalse(path.exists())

    def test_linked_tsunami_cause_survives_priority_reconciliation(self):
        rows = self.floods()[:2]
        rows[0]['cause'] = 'tsunami'
        rows[1]['cause'] = 'Flood (General)'
        path = self.csv(rows)
        self.assertEqual(len(c.load_flood_event_dates(path, 1000, False)), 1)
        self.assertEqual(c.load_flood_event_dates(path, 1000, True), [])

    def test_gtd_gap_distinct_from_observed_zero(self):
        path = self.csv([dict(year=1992, events=0, deaths=0), dict(year=1994, events=2, deaths=3)])
        out = c.load_yearly_terrorism_events(path, 1969, 2023)
        self.assertEqual(out.loc[1992], 0)
        self.assertTrue(out.loc[[1969, 1993, 2022, 2023]].isna().all())


if __name__ == '__main__':
    unittest.main()
