"""Frozen seasonal references, ISO boundaries, missingness and stream isolation."""
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from monitoring import seasonal_flu as flu


TARGET = date.fromisocalendar(2026, 20, 1)
AS_OF = (TARGET + timedelta(days=13)).isoformat()


def observation(start, positive=20, tested=100, **extra):
    row = dict(country='AAA', period_start=start.isoformat(), period_end=(start + timedelta(days=6)).isoformat(),
               metric='influenza_positivity', value=positive / tested if tested else None, unit='positive_fraction',
               numerator=positive, denominator=tested, frequency='weekly', source_id='who', source_version='fixture-v1',
               source_url='https://example.test/sentinel', published_at=None, fetched_at=None, provisional=True,
               dimensions=json.dumps({'surveillance_origin': 'SENTINEL'}), quality_note='fixture')
    row.update(extra)
    return row


def window(year, week=20, positive=20, tested=100, **extra):
    center = date.fromisocalendar(year, min(week, date(year, 12, 28).isocalendar().week), 1)
    return [observation(center + timedelta(weeks=offset), positive, tested, **extra) for offset in range(-2, 3)]


def complete_fixture(positive=40):
    return sum([window(year) for year in (2023, 2024, 2025)], []) + [observation(TARGET, positive)]


def calculate(rows, as_of=AS_OF, **overrides):
    return flu.seasonal_flu(pd.DataFrame(rows), as_of,
                            dict(target_weeks=1, expected_countries=['AAA']) | overrides)


class SeasonalFluTests(unittest.TestCase):
    def test_runtime_plan_uses_committed_pre_analysis_contract(self):
        path = Path(flu.__file__).with_name('extension_plan.json')
        self.assertEqual(flu.PLAN, json.loads(path.read_text())['seasonal_flu'])
        with self.assertRaisesRegex(ValueError, 'Unknown seasonal-flu plan'):
            calculate([], arbitrary_threshold=5)

    def test_specimen_weighting_within_windows_and_equal_median_across_years(self):
        first = window(2023, positive=0)
        first[0] = observation(date.fromisocalendar(2023, 18, 1), positive=100, tested=1000)
        rows = first + window(2024, positive=20) + window(2025, positive=270, tested=900) + [observation(TARGET, 40)]
        result = calculate(rows)
        row = result.iloc[0]
        self.assertEqual(row.status, 'available')
        self.assertAlmostEqual(row.baseline_positivity, .2)
        self.assertAlmostEqual(row.observed_positivity, .4)
        self.assertAlmostEqual(row.difference_percentage_points, 20.)
        self.assertAlmostEqual(row.positivity_ratio, 2.)
        windows = pd.DataFrame(result.attrs['baseline_windows'])
        self.assertAlmostEqual(windows.loc[windows.baseline_center_iso_year.eq(2023), 'positivity'].iloc[0], 100 / 1400)
        self.assertEqual(row.qualified_baseline_windows, 3)
        self.assertTrue(row.source_provisional)
        self.assertEqual(row.reporting_site_coverage, 'unverified')

    def test_absent_expected_weeks_and_countries_are_retained_without_using_stale_week(self):
        rows = complete_fixture()[:-1] + [observation(TARGET - timedelta(weeks=1), 50)]
        result = calculate(rows, target_weeks=3, expected_countries=['AAA', 'BBB'])
        self.assertEqual(len(result), 6)
        latest = result[result.latest_expected_week]
        self.assertTrue(latest.status.eq('unobserved_week').all())
        self.assertTrue(latest.observed_positivity.isna().all())
        self.assertTrue(result[result.country.eq('BBB')].denominator.isna().all())
        report = '\n'.join(flu.report_lines(result))
        self.assertIn('2026-W20', report)
        self.assertNotIn('2026-W19', report)
        self.assertNotIn('50.0%', report)

    def test_sentinel_origin_version_and_all_dimension_streams_remain_separate(self):
        rows = complete_fixture()
        non_sentinel = [dict(row, dimensions=json.dumps({'surveillance_origin': 'NON_SENTINEL'}), numerator=99, value=.99) for row in rows]
        different = [dict(row, source_version='fixture-v2', numerator=90, value=.9) for row in rows]
        age_group = [observation(TARGET, 10, dimensions=json.dumps({'surveillance_origin': 'SENTINEL', 'age_group': 'children'}))]
        result = calculate(rows + non_sentinel + different + age_group)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[result.source_version.eq('fixture-v2')].baseline_positivity.iloc[0], .9)
        adult = result[result.dimensions.eq('{"surveillance_origin":"SENTINEL"}') & result.source_version.eq('fixture-v1')].iloc[0]
        self.assertEqual(adult.baseline_positivity, .2)
        child = result[result.dimensions.str.contains('children')].iloc[0]
        self.assertEqual(child.status, 'insufficient_baseline')
        self.assertEqual(child.qualified_baseline_windows, 0)

    def test_iso_week53_year_boundary_and_current_iso_year_exclusion(self):
        target = date.fromisocalendar(2020, 53, 1)
        rows = sum([window(year, week=53, positive=10) for year in range(2015, 2020)], []) + [observation(target, 40)]
        as_of = (target + timedelta(days=13)).isoformat()
        result = calculate(rows, as_of)
        current = result.iloc[0]
        self.assertEqual((current.iso_year, current.iso_week), (2020, 53))
        self.assertEqual(current.period_end, '2021-01-03')
        windows = pd.DataFrame(result.attrs['baseline_windows'])
        first = windows[windows.baseline_center_iso_year.eq(2015)].iloc[0]
        last = windows[windows.baseline_center_iso_year.eq(2019)].iloc[0]
        self.assertEqual(first.baseline_center_iso_week, 53)
        self.assertFalse(first.week53_mapped_to52)
        self.assertEqual(last.baseline_center_iso_week, 52)
        self.assertTrue(last.week53_mapped_to52)
        self.assertEqual(last.eligible_weeks, 3)
        self.assertFalse(last.qualified)
        self.assertEqual(json.loads(last.excluded_week_reasons)['not_strictly_prior_target_iso_year'], 2)
        changed = [dict(row, numerator=99, value=.99) if date.fromisoformat(row['period_start']).isocalendar().year == 2020 and row['period_start'] != target.isoformat() else row for row in rows]
        changed += [observation(date.fromisocalendar(2021, 20, 1), 99)]
        later = calculate(changed, as_of)
        self.assertEqual(current.baseline_positivity, later.iloc[0].baseline_positivity)
        self.assertEqual(current.difference_percentage_points, later.iloc[0].difference_percentage_points)

    def test_week1_references_use_adjacent_real_dates_not_fractional_year_offsets(self):
        target = date.fromisocalendar(2021, 1, 1)
        rows = sum([window(year, week=1) for year in (2018, 2019, 2020)], []) + [observation(target)]
        result = calculate(rows, (target + timedelta(days=13)).isoformat())
        self.assertEqual(result.iloc[0].status, 'available')
        historical = pd.DataFrame(result.attrs['baseline_windows'])
        row = historical[historical.baseline_center_iso_year.eq(2020)].iloc[0]
        self.assertEqual(row.window_start, '2019-12-16')
        self.assertEqual(row.window_end, '2020-01-19')
        self.assertEqual(row.eligible_weeks, 5)

    def test_calendar_lag_partial_weeks_and_explicit_partial_reporting(self):
        result = calculate(complete_fixture(), (TARGET + timedelta(days=12)).isoformat())
        self.assertEqual(result.iloc[0].period_start, (TARGET - timedelta(weeks=1)).isoformat())
        self.assertTrue(any(row['reason'] == 'reporting_lag' for row in result.attrs['row_quality']))
        partial = complete_fixture(); partial[-1]['period_end'] = (TARGET + timedelta(days=3)).isoformat()
        self.assertEqual(calculate(partial).iloc[0].status, 'incomplete_or_invalid_iso_week')
        partial = complete_fixture(); partial[-1]['reporting_complete'] = False
        self.assertEqual(calculate(partial).iloc[0].status, 'explicit_partial_reporting')

    def test_baseline_missing_week_coverage_is_not_filled_with_zero(self):
        rows = window(2023)[:-1] + window(2024)[:-1] + window(2025)[:-1] + [observation(TARGET)]
        good = calculate(rows).iloc[0]
        self.assertEqual(good.status, 'available')
        self.assertEqual(good.eligible_baseline_weeks, 12)
        self.assertEqual(good.baseline_positivity, .2)
        rows = window(2023)[:-1] + window(2024)[:-1] + window(2025)[:-2] + [observation(TARGET)]
        result = calculate(rows).iloc[0]
        self.assertEqual(result.status, 'insufficient_baseline')
        self.assertEqual(result.qualified_baseline_windows, 2)
        self.assertTrue(pd.isna(result.baseline_positivity))
        self.assertTrue(pd.isna(result.difference_percentage_points))

    def test_low_testing_invalid_counts_and_missing_counts_stay_unavailable(self):
        for changes, status in [({'numerator': 10, 'denominator': 99, 'value': 10/99}, 'low_testing'),
                                 ({'denominator': 0}, 'invalid_specimen_counts'),
                                 ({'numerator': 101}, 'invalid_specimen_counts'),
                                 ({'numerator': .5}, 'invalid_specimen_counts'),
                                 ({'numerator': None, 'value': 0}, 'missing_specimen_counts'),
                                 ({'value': .99}, 'inconsistent_reported_positivity'),
                                 ({'unit': 'percent'}, 'incompatible_unit_or_frequency')]:
            rows = complete_fixture(); rows[-1].update(changes)
            with self.subTest(status=status, changes=changes):
                result = calculate(rows).iloc[0]
                self.assertEqual(result.status, status)
                self.assertTrue(pd.isna(result.observed_positivity))
                self.assertTrue(pd.isna(result.difference_percentage_points))

    def test_true_zero_positivity_is_observed_but_zero_baseline_ratio_undefined(self):
        rows = sum([window(year, positive=0) for year in (2023, 2024, 2025)], []) + [observation(TARGET, 0)]
        result = calculate(rows).iloc[0]
        self.assertEqual(result.status, 'available')
        self.assertEqual(result.observed_positivity, 0)
        self.assertEqual(result.baseline_positivity, 0)
        self.assertEqual(result.difference_percentage_points, 0)
        self.assertTrue(pd.isna(result.positivity_ratio))
        self.assertEqual(result.ratio_status, 'baseline_zero')

    def test_duplicate_and_projected_weeks_never_chosen_or_pooled(self):
        duplicate = complete_fixture() + [observation(TARGET, 90)]
        result = calculate(duplicate)
        self.assertEqual(result.iloc[0].status, 'duplicate_stream_week')
        self.assertEqual(sum(row['reason'] == 'duplicate_stream_week' for row in result.attrs['row_quality']), 2)
        projected = complete_fixture(); projected[-1]['projected'] = True
        self.assertEqual(calculate(projected).iloc[0].status, 'projected_observation')

    def test_as_of_availability_and_date_only_end_of_day_are_explicit(self):
        rows = complete_fixture(); rows[-1]['fetched_at'] = AS_OF + 'T12:00:00Z'
        self.assertEqual(calculate(rows).iloc[0].status, 'available')
        self.assertEqual(calculate(rows, AS_OF + 'T11:00:00Z').attrs['row_quality'][-1]['reason'], 'reporting_lag')
        next_day = (date.fromisoformat(AS_OF) + timedelta(days=1)).isoformat()
        rows[-1]['fetched_at'] = next_day + 'T12:00:00Z'
        self.assertEqual(calculate(rows, next_day + 'T11:00:00Z').iloc[0].status, 'not_available_as_of')
        rows[-1]['fetched_at'] = AS_OF + 'T12:00:00Z'
        rows[-1]['published_at'] = (date.fromisoformat(AS_OF) + timedelta(days=1)).isoformat()
        self.assertEqual(calculate(rows).iloc[0].status, 'not_available_as_of')

    def test_exact_sunday_cutoff_requires_complete_week_plus_elapsed_reporting_lag(self):
        for stamp in [AS_OF + 'T02:00:00Z', AS_OF + 'T23:59:59Z',
                      (date.fromisoformat(AS_OF) - timedelta(days=1)).isoformat() + 'T22:00:00-05:00']:
            with self.subTest(stamp=stamp):
                result = calculate(complete_fixture(), stamp)
                self.assertEqual(result.iloc[0].period_start, (TARGET - timedelta(weeks=1)).isoformat())
                self.assertEqual(result.attrs['row_quality'][-1]['reason'], 'reporting_lag')
        for stamp in [AS_OF, date.fromisoformat(AS_OF), AS_OF + 'T23:59:59.999999999Z',
                      (date.fromisoformat(AS_OF) + timedelta(days=1)).isoformat() + 'T00:00:00Z']:
            with self.subTest(stamp=stamp):
                result = calculate(complete_fixture(), stamp)
                self.assertEqual(result.iloc[0].period_start, TARGET.isoformat())
                self.assertEqual(result.iloc[0].status, 'available')

    def test_zero_lag_still_requires_whole_sunday_to_finish(self):
        sunday = (TARGET + timedelta(days=6)).isoformat()
        result = calculate(complete_fixture(), sunday + 'T12:00:00Z', reporting_lag_days=0)
        self.assertEqual(result.attrs['row_quality'][-1]['reason'], 'calendar_week_not_complete')
        self.assertEqual(result.iloc[0].period_start, (TARGET - timedelta(weeks=1)).isoformat())
        self.assertEqual(calculate(complete_fixture(), sunday, reporting_lag_days=0).iloc[0].status, 'available')

    def test_empty_data_exports_explicit_unavailable_rows_and_valid_empty_diagnostic_headers(self):
        result = calculate([])
        self.assertEqual(result.iloc[0].status, 'unobserved_week')
        self.assertTrue(pd.isna(result.iloc[0].numerator))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = flu.write_outputs(result, root)
            before = {path.name: path.stat().st_mtime_ns for path in root.iterdir()}
            flu.write_outputs(result, root)
            self.assertEqual(before, {path.name: path.stat().st_mtime_ns for path in root.iterdir()})
            self.assertEqual(len(pd.read_csv(root / 'seasonal_flu_row_quality.csv')), 0)
            self.assertEqual(manifest['status_counts'], {'unobserved_week': 1})
            self.assertEqual(manifest['plan'], result.attrs['plan'])
            self.assertNotIn('p_value', pd.read_csv(root / 'seasonal_flu_weekly.csv').columns)


if __name__ == '__main__':
    unittest.main()
