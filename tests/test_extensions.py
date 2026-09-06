"""Exercise extension wiring with synthetic sources and the real output writers."""
from contextlib import ExitStack, redirect_stdout
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from monitoring import analysis, climate_controls, extensions, seasonal_flu


LOADERS = {
    'load_yearly_quakes_m7': ('eq_db_1900', '../earthquakes/quakes_1900.sqlite'),
    'load_yearly_war_deaths_active': ('wars_csv', 'data/wars.csv'),
    'load_yearly_famine_deaths_wpf': ('famines_wpf_csv', 'data/famine_deaths_by_year.csv'),
    'load_yearly_flood_deaths': ('floods_csv', 'data/floods.csv'),
    'load_yearly_pandemic_deaths': ('pandemics_csv', 'data/pandemics.csv'),
    'load_yearly_volcanoes': ('volcanoes_csv', 'data/volcanoes.csv'),
    'load_yearly_cyclone_deaths': ('cyclones_csv', 'data/cyclones.csv'),
    'load_yearly_flares_x1': ('flares_csv', 'data/flares_xclass.csv'),
    'load_yearly_terrorism_deaths': ('terrorism_csv', 'data/terrorism.csv'),
    'load_yearly_stock_drawdown_intensity': ('crashes_csv', 'data/stock_crashes.csv'),
}


def fixture():
    rng = np.random.default_rng(731)
    years = np.arange(1976, 2026)
    x = pd.Series(rng.normal(size=len(years)), index=years)
    y = 2 * x + rng.normal(scale=.03, size=len(years))
    series = {'M>=7 quakes': (x, 'quakes_m7'), 'War deaths log10': (y, 'wars_global')}
    annual = pd.DataFrame({'year': years, 'rni': rng.normal(size=len(years)),
                           'dmi': rng.normal(size=len(years))})
    panel = pd.DataFrame([{'country': 'ETH', 'year': year, 'metric': metric,
                           'value': value, 'geographic_scope': 'source country definition'}
                          for metric, values in [('conflict_total_deaths_per_100k', 20 + x),
                                                  ('refugees_origin_stock_change', 40 + y)]
                          for year, value in values.items()])
    columns = ['index', 'period_start', 'period_end', 'value', 'usable', 'source_version']
    monthly = pd.DataFrame([
        ['rni', '2026-08-01', '2026-08-31', .35, True, 'fixture RNI'],
        ['rni', '2026-09-01', '2026-09-30', 999.0, True, 'future RNI'],
        ['dmi', '2026-08-01', '2026-08-31', -.12, True, 'fixture DMI']], columns=columns)
    seasonal = pd.DataFrame([
        ['roni', '2026-05-01', '2026-07-31', .8, True, 'fixture RONI'],
        ['roni', '2026-07-01', '2026-09-30', 999.0, True, 'future RONI']], columns=columns)
    climate = {'annual.csv': annual, 'monthly.csv': monthly, 'roni_seasonal.csv': seasonal}
    source = {'snapshot_id': 'synthetic-climate-snapshot',
              'versions': {'rni': 'fixture RNI', 'dmi': 'fixture DMI', 'roni': 'fixture RONI'}}
    return series, panel, climate, source


class ExtensionLoaders(unittest.TestCase):
    def test_all_ten_loaders_match_original_matrix_calls_and_regimes(self):
        import correlate_events
        import meta_analysis

        root = Path('/synthetic-workspace/correlations')
        args = SimpleNamespace(year_hi=2025, n_boot=1)
        for _, (argument, relative) in LOADERS.items():
            setattr(args, argument, root.parent/'earthquakes/quakes_1900.sqlite'
                    if argument == 'eq_db_1900' else root/relative)
        mocks = {name: Mock(return_value=pd.Series([float(i), np.nan], index=[2024, 2025]))
                 for i, name in enumerate(LOADERS)}
        captured = {}

        class StopBeforeMatrixInference(Exception):
            pass

        def capture_original(series, **kwargs):
            captured.update(series)
            raise StopBeforeMatrixInference

        with ExitStack() as stack:
            for name, mock in mocks.items():
                stack.enter_context(patch.object(correlate_events, name, mock))
                stack.enter_context(patch.object(meta_analysis, name, mock))
            stack.enter_context(patch.object(extensions, 'last_complete_year', return_value=2025))
            stack.enter_context(patch.object(meta_analysis, 'cross_correlation_tests', side_effect=capture_original))
            new = extensions.load_global_series(root, end_year=2099)
            new_calls = {name: mock.call_args for name, mock in mocks.items()}
            for mock in mocks.values():
                mock.assert_called_once()
                mock.reset_mock()
            with redirect_stdout(io.StringIO()), self.assertRaises(StopBeforeMatrixInference):
                meta_analysis.run_cross_corr_matrix(args, root/'unused-output')
            self.assertEqual(list(new.items()), list(captured.items()))
            self.assertEqual([(name, value[1]) for name, value in new.items()],
                             list(climate_controls.GLOBAL_SERIES_SPEC))
            for name, mock in mocks.items():
                with self.subTest(loader=name):
                    mock.assert_called_once_with(*new_calls[name].args, **new_calls[name].kwargs)
                    self.assertEqual(new_calls[name].args[-1], 2025)


class ExtensionArtifacts(unittest.TestCase):
    def test_real_fit_report_outputs_hashes_and_expected_missing_countries(self):
        series, panel, climate, source = fixture()
        observations = pd.DataFrame()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            snapshot = base/'climate'; snapshot.mkdir()
            source_path = snapshot/'manifest.json'
            source_path.write_text(json.dumps(source))
            output = base/'extensions'
            with patch.object(extensions, 'load_snapshot', return_value=(climate, source)), \
                 patch.object(climate_controls, 'last_complete_year', return_value=2025):
                manifest = extensions.run(observations, panel, output, as_of='2026-09-05',
                                          climate_root=snapshot, global_series=series)
            report = (output/'extensions_report.md').read_text()
            global_table = pd.read_csv(output/'global_climate_sensitivity.csv')
            regional_table = pd.read_csv(output/'regional_climate_sensitivity.csv')
            self.assertEqual((len(global_table), len(regional_table)), (90, 144))
            self.assertGreater(manifest['global_passing_fits'], 0)
            self.assertGreater(manifest['regional_passing_fits'], 0)
            passing = pd.concat([global_table[global_table.reject_fdr],
                                 regional_table[regional_table.reject_fdr]])
            for row in passing.itertuples():
                with self.subTest(family=row.family, pair=row.pair_id, fit=row.fit):
                    self.assertIn(f'| {row.family} / {row.country} | {row.predictor} → {row.response} | '
                                  f'{row.lag_years} | {row.fit} | {int(row.response_start_year)}–'
                                  f'{int(row.response_end_year)} | {row.partial_r:+.3f} | {row.q_family:.4f} |', report)
            self.assertIn('2026-05-01–2026-07-31', report)
            self.assertNotIn('999.00', report)
            self.assertEqual(manifest['report_date'], '2026-09-05')
            self.assertEqual(manifest['as_of_utc'], '2026-09-06T04:59:59.999999999+00:00')
            flu = pd.read_csv(output/'seasonal_flu_weekly.csv')
            latest = flu[flu.latest_expected_week]
            self.assertEqual(set(latest.country), set(seasonal_flu.PLAN['expected_countries']))
            self.assertEqual(set(latest.period_end), {'2026-08-23'})
            self.assertTrue(latest.observed_positivity.isna().all())
            coverage = pd.read_csv(output/'affordability_coverage.csv')
            self.assertEqual(set(coverage.country), set(seasonal_flu.PLAN['expected_countries']))
            for country in latest.country:
                self.assertIn(f'| {country} / ', report)
                self.assertIn(f'| {country} | No validated exact pairs |', report)
                self.assertIn(f'| {country} | No eligible fixed basket |', report)
            self.assertEqual(manifest['flu_expected_week_end'], '2026-08-23')
            self.assertEqual(manifest['affordability_last_complete_month'], '2026-08')
            self.assertEqual(manifest['climate_snapshot_id'], source['snapshot_id'])
            self.assertEqual(manifest['climate_manifest_sha256'], hashlib.sha256(source_path.read_bytes()).hexdigest())
            self.assertEqual(manifest['observation_fingerprint'], extensions._fingerprint(observations))
            self.assertEqual(manifest['annual_panel_fingerprint'], extensions._fingerprint(panel))
            self.assertEqual(manifest['global_series_fingerprints'],
                             {name: extensions._fingerprint(value[0]) for name, value in series.items()})
            self.assertEqual(manifest['extension_plan_sha256'],
                             hashlib.sha256(Path(extensions.__file__).with_name('extension_plan.json').read_bytes()).hexdigest())
            self.assertEqual(json.loads((output/'extensions_manifest.json').read_text()), manifest)
            expected = {'global_climate_sensitivity.csv', 'global_climate_sensitivity.json',
                        'regional_climate_sensitivity.csv', 'regional_climate_sensitivity.json',
                        'climate_controls_metadata.json', 'climate_controls_report.md',
                        'seasonal_flu_weekly.csv', 'seasonal_flu_baseline_windows.csv',
                        'seasonal_flu_row_quality.csv', 'seasonal_flu.md', 'seasonal_flu_manifest.json',
                        'affordability_monthly.csv', 'affordability_latest_series.csv',
                        'affordability_series_annual.csv', 'affordability_basket_members.csv',
                        'affordability_basket_monthly.csv', 'affordability_basket_annual.csv',
                        'affordability_coverage.csv', 'affordability_diagnostics.csv',
                        'affordability_manifest.json', 'affordability.md', 'extensions_report.md'}
            self.assertEqual(set(manifest['outputs']), expected)
            for name, digest in manifest['outputs'].items():
                self.assertEqual(digest, hashlib.sha256((output/name).read_bytes()).hexdigest())
                if name.endswith('.csv'):
                    pd.read_csv(output/name)  # Empty diagnostics still require readable headers.

    def test_exact_timestamp_is_preserved_for_source_availability_and_week_cutoff(self):
        series, panel, climate, source = fixture()
        observations = pd.DataFrame([dict(country='ISR', source_id='who', source_version='fixture',
            source_url='https://example.test/WHO', metric='influenza_positivity', frequency='weekly',
            unit='positive_fraction', period_start='2026-08-17', period_end='2026-08-23',
            numerator=20, denominator=100, value=.2, published_at=None,
            fetched_at='2026-09-06T02:00:00Z', provisional=True,
            dimensions=json.dumps({'surveillance_origin': 'SENTINEL'}))])
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); (base/'manifest.json').write_text(json.dumps(source))
            with patch.object(extensions, 'load_snapshot', return_value=(climate, source)), \
                 patch.object(climate_controls, 'last_complete_year', return_value=2025):
                manifest = extensions.run(observations, panel, base/'out', as_of='2026-09-05T22:00:00-05:00',
                                          climate_root=base, global_series=series)
            self.assertEqual(manifest['as_of_utc'], '2026-09-06T03:00:00+00:00')
            self.assertEqual(manifest['report_date'], '2026-09-05')
            quality = pd.read_csv(base/'out/seasonal_flu_row_quality.csv')
            self.assertEqual(quality.reason.tolist(), ['eligible'])
            flu = pd.read_csv(base/'out/seasonal_flu_weekly.csv')
            row = flu[flu.latest_expected_week & flu.country.eq('ISR')].iloc[0]
            self.assertEqual(row.period_end, '2026-08-23')
            self.assertEqual(row.observed_positivity, .2)
            self.assertEqual(row.status, 'insufficient_baseline')

    def test_failed_source_validation_never_writes_success_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch.object(extensions, 'load_snapshot', side_effect=ValueError('source hash mismatch')):
                with self.assertRaisesRegex(ValueError, 'source hash mismatch'):
                    extensions.run(pd.DataFrame(), pd.DataFrame(), output, as_of='2026-09-05', global_series={})
            self.assertFalse((output/'extensions_manifest.json').exists())


class AnnualAnalysisIntegration(unittest.TestCase):
    def test_analysis_main_uses_one_aware_cutoff_and_only_links_successful_extensions(self):
        stamp = pd.Timestamp('2026-09-05T22:00:00-05:00').to_pydatetime()
        observations = pd.DataFrame({'fixture': [1]})
        panel = pd.DataFrame({'fixture': [2]})
        tests = pd.DataFrame({'fixture': [3]})
        sync = pd.DataFrame({'fixture': [4]})
        for failing in (False, True):
            with self.subTest(extension_failure=failing), tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
                output = Path(temporary)
                stack.enter_context(patch.object(sys, 'argv', ['analysis', '--out', str(output), '--permutations', '7']))
                clock = stack.enter_context(patch.object(analysis, 'dt'))
                clock.datetime.now.return_value = stamp
                stack.enter_context(patch.object(analysis, 'load_observations', return_value=observations))
                build = stack.enter_context(patch.object(analysis, 'build_annual_panel', return_value=panel))
                lag = stack.enter_context(patch.object(analysis, 'lag_tests', return_value=tests))
                stack.enter_context(patch.object(analysis, 'synchrony', return_value=sync))
                write = stack.enter_context(patch.object(analysis, 'write_report',
                    side_effect=lambda *args, **kwargs: (output/'monitoring_report.md').write_text('Annual report\n')))
                run = stack.enter_context(patch.object(extensions, 'run',
                    side_effect=ValueError('extension failure') if failing else None))
                with redirect_stdout(io.StringIO()):
                    if failing:
                        with self.assertRaisesRegex(ValueError, 'extension failure'):
                            analysis.main()
                    else:
                        analysis.main()
                build.assert_called_once_with(observations, as_of=dt.date(2026, 9, 5))
                lag.assert_called_once_with(panel, n_permutations=7)
                write.assert_called_once_with(observations, panel, tests, sync, output,
                                               as_of=dt.date(2026, 9, 5), n_permutations=7)
                run.assert_called_once_with(observations, panel, output/'extensions', as_of=stamp)
                self.assertEqual('extensions/extensions_report.md' in (output/'monitoring_report.md').read_text(), not failing)


if __name__ == '__main__':
    unittest.main()
