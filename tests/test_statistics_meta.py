"""Coverage, dependence, and selection regressions for secondary analyses."""
import unittest
import numpy as np
import pandas as pd

from meta_analysis import (bootstrap_window_ratio, independent_block_correlation_test,
                           cross_correlation_tests, benjamini_hochberg)
from trends_meta import fit_slope_bootstrap
from sensitivity import jackknife_corr, selected_year_slope
from make_figures import descriptive_window_ratios, ratio_upper


class MetaStatisticsTests(unittest.TestCase):
    def test_matrix_keeps_all45_planned_pairs_when_one_catalogue_missing(self):
        rng = np.random.default_rng(772)
        series = {f"series{i}": (pd.Series(rng.normal(size=50), index=range(1950, 2000)), "")
                  for i in range(10)}
        series["series0"] = (pd.Series(np.nan, index=range(1950, 2000)), "")
        result = cross_correlation_tests(series, n_boot=50)
        self.assertEqual(len(result), 45)
        self.assertEqual(result.p.isna().sum(), 9)
        self.assertTrue((result.family_size == 45).all())
        self.assertEqual(result[result.a == "series0"].n.sum(), 0)
        _, expected = benjamini_hochberg(result.p)
        np.testing.assert_allclose(result.q, expected, equal_nan=True)

    def test_block_null_retains_prespecified_sensitivity_family(self):
        rng = np.random.default_rng(95)
        x = rng.normal(size=100)
        result = independent_block_correlation_test(x, x + rng.normal(0, .03, 100), n_boot=200)
        self.assertGreater(result["r"], .99)
        self.assertEqual(result["p"], max(result[f"p_block_{n}"] for n in [3, 5, 10]))
        self.assertLess(result["p"], .01)
        invalid = independent_block_correlation_test(np.ones(100), x, n_boot=100)
        self.assertTrue(np.isnan(invalid["p"]))

    def test_missing_coverage_never_turns_into_zero_slope(self):
        result = fit_slope_bootstrap(range(1985, 2020), np.full(35, np.nan), n_boot=50)
        self.assertEqual(result["n_years"], 0)
        self.assertTrue(np.isnan(result["slope_per_decade"]))
        self.assertIn("contiguous", result["status"])

    def test_trend_uses_contiguous_observed_years_and_correct_interval(self):
        years = np.arange(1950, 2000)
        values = 3 * (years - 1950).astype(float)
        values[10] = np.nan
        result = fit_slope_bootstrap(years, values, n_boot=100)
        self.assertEqual((result["start_year"], result["end_year"]), (1961, 1999))
        self.assertAlmostEqual(result["slope_per_decade"], 30)
        self.assertAlmostEqual(result["ci_lo_per_decade"], 30)
        self.assertAlmostEqual(result["ci_hi_per_decade"], 30)

    def test_selected_year_sensitivity_never_reports_iid_significance(self):
        rng = np.random.default_rng(96)
        a = pd.Series(rng.normal(size=80), index=range(1900, 1980))
        b = a + rng.normal(0, .2, size=80)
        b.loc[1920] = np.nan
        result = jackknife_corr(a, b, "", "", 3, 3)
        self.assertTrue(np.isnan(result["p"]))
        self.assertEqual(result["start_year"], 1921)
        self.assertTrue(all(year >= 1921 for year in result["dropped"]))
        self.assertEqual(result["n"] + len(result["dropped"]), 59)

    def test_raw_slope_deletion_keeps_actual_calendar_distances(self):
        years = np.arange(1900, 1950)
        s = pd.Series(2 * (years - 1900), index=years)
        result = selected_year_slope(s, 5)
        self.assertAlmostEqual(result["slope"], 20)
        self.assertEqual(result["n"], 45)
        self.assertEqual(set(result["dropped"]), set(range(1945, 1950)))

    def test_daily_ratios_remove_targets_outside_observed_exposure(self):
        first, missing, third = pd.date_range("2000-01-01", periods=3)
        result = descriptive_window_ratios([first], [first, missing], {first, third}, [0], modes=("centered",))
        self.assertEqual(result.n_targets.iloc[0], 1)
        self.assertEqual(result.ratio.iloc[0], 2)

    def test_no_event_window_never_plots_fabricated_ratio_one(self):
        date = pd.Timestamp("2000-01-01")
        result = descriptive_window_ratios([], [date], {date}, [0])
        self.assertTrue(result.ratio.isna().all())
        self.assertEqual(ratio_upper(result.ratio), 1.2)

    def test_empty_window_ratio_is_unavailable_not_zero_effect(self):
        dates = pd.date_range("2000-01-01", "2005-12-31")
        result = bootstrap_window_ratio([], [dates[0]], dates, 0, n_boot=50)
        self.assertTrue(np.isnan(result["point_estimate"]))
        self.assertIn("unavailable", result["status"])


if __name__ == "__main__":
    unittest.main()
