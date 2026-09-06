"""Synthetic regression tests fixed before inspecting adjusted historical fits."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

from monitoring import climate_controls as C


def fixture(years=None, seed=1729):
    years = np.arange(1950, 2026) if years is None else np.asarray(years)
    rng = np.random.default_rng(seed)
    climate = pd.DataFrame({"year": years, "rni": rng.normal(size=len(years)),
                            "dmi": rng.normal(size=len(years))})
    x = pd.Series(5 * climate.rni.to_numpy() + rng.normal(size=len(years)), index=years)
    y = pd.Series(5 * climate.rni.to_numpy() + rng.normal(size=len(years)), index=years)
    return x, y, climate


def global_sources(x, y):
    return {C.GLOBAL_SERIES_SPEC[0][0]: x, C.GLOBAL_SERIES_SPEC[1][0]: y}


def regional_panel(x, y, *, country="ETH", ipc_scope="verified comparable assessment geography"):
    metrics = {C.REGIONAL_PAIRS[0][0]: x, C.REGIONAL_PAIRS[0][1]: y,
               C.REGIONAL_PAIRS[1][1]: y / 100, C.REGIONAL_PAIRS[2][0]: x / 10}
    return pd.DataFrame([{"country": country, "year": year, "metric": metric,
                          "value": value, "geographic_scope": ipc_scope}
                         for metric, series in metrics.items() for year, value in series.items()])


class PairedClimateSamples(unittest.TestCase):
    def test_missing_year_splits_sample_and_both_fits_have_exact_same_values(self):
        x, y, climate = fixture()
        climate.loc[climate.year.eq(1980), "dmi"] = np.nan
        result = C.global_climate_sensitivity(global_sources(x, y), climate, end_year=2025).iloc[:2]
        self.assertEqual(result.n.tolist(), [45, 45])
        self.assertEqual(result.response_start_year.tolist(), [1981, 1981])
        self.assertEqual(result.sample_sha256.nunique(), 1)
        self.assertEqual(result.sample_years.nunique(), 1)
        self.assertNotIn("1980", result.sample_years.iloc[0])

    def test_ties_choose_earliest_contiguous_overlap(self):
        x, y, climate = fixture(np.arange(2000, 2021))
        climate.loc[climate.year.eq(2010), "rni"] = np.nan
        sample = C.paired_sample(x, y, climate, end_year=2020)
        self.assertEqual(sample.index.tolist(), list(range(2000, 2010)))

    def test_lag_has_both_climate_times_and_never_uses_future_climate(self):
        x, y, climate = fixture(np.arange(2000, 2027))
        with patch.object(C, "last_complete_year", return_value=2025):
            sample = C.paired_sample(x, y, climate, lag=2, end_year=2030)
        self.assertEqual(sample.index.max(), 2025)
        self.assertEqual(sample.loc[2010, "x"], x.loc[2008])
        self.assertEqual(sample.loc[2010, "y"], y.loc[2010])
        self.assertEqual(sample.loc[2010, "rni_predictor"], climate.set_index("year").loc[2008, "rni"])
        self.assertEqual(sample.loc[2010, "dmi_response"], climate.set_index("year").loc[2010, "dmi"])
        self.assertEqual(sample.index.min(), 2002)

    def test_source_or_climate_schema_errors_are_not_silent_unavailability(self):
        x, y, climate = fixture()
        with self.assertRaisesRegex(ValueError, "duplicate annual years"):
            C.paired_sample(x, y, pd.concat([climate, climate.iloc[:1]]))
        with self.assertRaisesRegex(ValueError, "seasonal roni"):
            C.paired_sample(x, y, climate.rename(columns={"rni": "roni"}))
        bad = x.copy()
        bad.index = bad.index.astype(float) + 0.5
        with self.assertRaisesRegex(ValueError, "finite integers"):
            C.paired_sample(bad, y, climate)


class ClimateInference(unittest.TestCase):
    def test_known_common_climate_driver_removed_without_changing_sample(self):
        x, y, climate = fixture()
        result = C.global_climate_sensitivity(global_sources(x, y), climate).iloc[:2]
        self.assertEqual(result.status.tolist(), ["eligible", "eligible"])
        self.assertGreater(result.partial_r.iloc[0], 0.9)
        self.assertLess(abs(result.partial_r.iloc[1]), 0.25)
        # A random null realization need not have raw p>0.05; the full family
        # must not turn this small remaining sample association into a finding.
        self.assertGreater(result.q_family.iloc[1], 0.05)
        self.assertEqual(result.sample_sha256.nunique(), 1)

    def test_independent_adjusted_slope_agrees_with_known_signal(self):
        x, _, climate = fixture(seed=93)
        rng = np.random.default_rng(420)
        # Predictor has additional independent variation beyond the climate terms.
        x = x + pd.Series(rng.normal(0, 2, len(x)), index=x.index)
        y = 2 * x + pd.Series(3 * climate.dmi.to_numpy() + rng.normal(0, .5, len(x)), index=x.index)
        result = C.global_climate_sensitivity(global_sources(x, y), climate).iloc[1]
        self.assertEqual(result.status, "eligible")
        self.assertAlmostEqual(result.beta, 2, delta=0.10)
        self.assertLess(result.beta_ci_low, 2)
        self.assertGreater(result.beta_ci_high, 2)
        self.assertEqual(result.df_resid, result.n - result["rank"])

    def test_singular_climate_does_not_fabricate_adjusted_fit(self):
        x, y, climate = fixture()
        climate["dmi"] = climate.rni
        result = C.global_climate_sensitivity(global_sources(x, y), climate).iloc[:2]
        self.assertEqual(result.status.iloc[0], "eligible")
        self.assertEqual(result.reason.iloc[1], "singular_controls")
        self.assertTrue(pd.isna(result.p_hac.iloc[1]))
        self.assertEqual(result.q_family.iloc[1], 1)

    def test_constant_and_time_explained_series_are_unavailable(self):
        x, y, climate = fixture()
        for values, expected in ((x * 0 + 1, "constant_series"),
                                 (pd.Series(x.index.astype(float), index=x.index), "constant_after_controls")):
            with self.subTest(expected=expected):
                result = C.global_climate_sensitivity(global_sources(values, y), climate).iloc[:2]
                self.assertTrue(result.reason.eq(expected).all())
                self.assertTrue(result.p_hac.isna().all())

    def test_minimum_residual_df_guards_short_lagged_adjusted_fit(self):
        x, y, climate = fixture(np.arange(2000, 2014))
        result = C.regional_climate_sensitivity(regional_panel(x, y), climate)
        cell = result[result.country.eq("ETH") & result.response.eq(C.REGIONAL_PAIRS[0][1])
                      & result.lag_years.eq(2)].reset_index(drop=True)
        self.assertEqual(cell.n.tolist(), [12, 12])
        self.assertEqual(cell.status.iloc[0], "eligible")
        self.assertEqual(cell.reason.iloc[1], "insufficient_residual_degrees_of_freedom")
        self.assertEqual(cell.df_resid.iloc[1], 5)

    def test_shared_fixed_regime_union_appears_in_both_fits(self):
        x, y, climate = fixture()
        result = C.global_climate_sensitivity(global_sources(x, y), climate).iloc[:2]
        self.assertEqual(result.n_controls.tolist(), [4, 6])
        for controls in result.control_columns:
            self.assertIn("intercept_1950_1988", controls)
            self.assertIn("time_1989_2025", controls)
        self.assertIn("rni_response", result.control_columns.iloc[1])


class ClimateFamiliesAndArtifacts(unittest.TestCase):
    def test_global_family_retains_all_missing_tests_and_both_model_variants(self):
        x, y, climate = fixture()
        result = C.global_climate_sensitivity(global_sources(x, y), climate)
        self.assertEqual(len(result), 90)
        self.assertEqual(result.pair_id.nunique(), 45)
        self.assertEqual(result.status.eq("eligible").sum(), 2)
        self.assertTrue(result.family_size.eq(90).all())
        expected = multipletests(result.p_hac.fillna(1), method="fdr_bh")[1]
        np.testing.assert_allclose(result.q_family, expected)
        with self.assertRaisesRegex(ValueError, "outside fixed family"):
            C.global_climate_sensitivity({"new chosen predictor": x}, climate)
        with self.assertRaisesRegex(ValueError, "Changed fixed regime"):
            C.global_climate_sensitivity({C.GLOBAL_SERIES_SPEC[0][0]: (x, "famines")}, climate)

    def test_regional_family_preserves_geo_gates_and_signed_stock_changes(self):
        x, y, climate = fixture(np.arange(2000, 2026))
        panel = pd.concat([regional_panel(x, y, country=country, ipc_scope="unknown")
                           for country in ["ETH", "ISR", "SDN"]], ignore_index=True)
        result = C.regional_climate_sensitivity(panel, climate)
        self.assertEqual(len(result), 144)
        self.assertEqual(result.pair_id.nunique(), 72)
        self.assertTrue(result.family_size.eq(144).all())
        self.assertTrue(result[result.response.eq("ipc_current_3plus_fraction")].n.eq(0).all())
        self.assertTrue(result[result.country.eq("ISR")].n.eq(0).all())
        sudan = result[result.country.eq("SDN") & result.response.eq("refugees_origin_stock_change")]
        self.assertTrue(sudan.predictor_start_year.ge(2012).all())
        eth = result[result.country.eq("ETH") & result.response.eq("refugees_origin_stock_change")]
        self.assertTrue(eth.status.eq("eligible").all())
        self.assertTrue(eth["transform"].eq("signed_log1p").all())

    def test_recorded_plan_drift_fails_and_outputs_are_separate_valid_json(self):
        x, y, climate = fixture()
        with patch.object(C, "HAC_MAXLAGS", 4):
            with self.assertRaisesRegex(ValueError, "plan/runtime mismatch: hac_maxlags"):
                C.global_climate_sensitivity(global_sources(x, y), climate)
        global_table = C.global_climate_sensitivity(global_sources(x, y), climate)
        regional_table = C.regional_climate_sensitivity(regional_panel(x, y), climate)
        with tempfile.TemporaryDirectory() as directory:
            outputs = C.write_outputs(global_table, regional_table, directory)
            self.assertEqual(len(outputs), 6)
            for path in outputs:
                self.assertTrue(path.exists())
                if path.suffix == ".json":
                    self.assertNotIn("NaN", path.read_text())
                    json.loads(path.read_text())
            metadata = json.loads((Path(directory) / "climate_controls_metadata.json").read_text())
            self.assertEqual(metadata["global"]["family_size"], 90)
            self.assertEqual(metadata["regional"]["family_size"], 144)
            self.assertEqual(metadata["global"]["extension_plan_sha256"], C.validate_plan())


if __name__ == "__main__":
    unittest.main()
