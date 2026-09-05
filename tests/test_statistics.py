"""Regressions for the failures reproduced in the September 2026 review."""
import unittest
import tempfile
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd

from statistical_helpers import (bh_adjust, contiguous_overlap, baseline_z_score,
                                 domain_composite, residual_slope_ci)
from pattern_analysis import fit_gap_trend
from wavelet import cwt_coherence
from chains import lag_correlation_bootstrap
from contractions_analysis import find_contractions
from periodogram_extended import spectral_inference, raw_periodogram, red_noise_surrogates, load_g3_days
from granger import granger_family


class StatisticalRegressionTests(unittest.TestCase):
    def test_gap_interval_tracks_observed_trend(self):
        times = np.r_[0, np.cumsum(np.arange(20, 0, -1))]
        result = fit_gap_trend(times, n_boot=100)
        self.assertAlmostEqual(result["slope"], -1)
        self.assertAlmostEqual(result["ci_lo"], -1)
        self.assertAlmostEqual(result["ci_hi"], -1)

    def test_multiple_events_within_year_survive_timestamp_test(self):
        slow = fit_gap_trend(np.arange(10), n_boot=100)
        dense = fit_gap_trend(np.r_[np.arange(5), np.arange(5, 10, 0.1)], n_boot=100)
        self.assertEqual(slow["n_gaps"], 9)
        self.assertGreater(dense["n_gaps"], 50)
        self.assertLess(dense["slope"], 0)
        coarse = fit_gap_trend(np.floor(np.r_[np.arange(5), np.arange(5, 10, 0.1)]), n_boot=100, resolution="year")
        self.assertEqual(coarse["n_gaps"], 9)
        self.assertIn("within-year timing unavailable", coarse["interpretation"])

    def test_missing_year_never_collapses_time(self):
        index = np.arange(1900, 1950)
        a = pd.Series(np.sin(index), index=index)
        b = a.copy(); b.loc[1920] = np.nan; b.loc[1948:] = np.nan
        frame = contiguous_overlap({"a": a, "b": b})
        self.assertEqual(list(frame.index), list(range(1921, 1948)))
        self.assertTrue(np.isfinite(frame.to_numpy()).all())

    def test_wavelet_observed_overlap_has_finite_cells(self):
        t = np.arange(100)
        x = np.sin(2 * np.pi * t / 11)
        y = np.sin(2 * np.pi * (t - 2) / 11)
        coherence, phase = cwt_coherence(x, y, np.geomspace(2, 20, 12))
        self.assertEqual(coherence.shape, (12, 100))
        self.assertTrue(np.isfinite(coherence).all())
        self.assertTrue(((coherence >= 0) & (coherence <= 1)).all())
        with self.assertRaises(ValueError):
            cwt_coherence(np.r_[x[:-1], np.nan], y, np.geomspace(2, 20, 12))

    def test_bh_uses_complete_planned_family(self):
        q = bh_adjust([.001, .02, .03, np.nan])
        np.testing.assert_allclose(q[:3], [.004, .04, .04])
        self.assertTrue(np.isnan(q[3]))

    def test_granger_outputs_six_directions_times_five_orders(self):
        rng = np.random.default_rng(914)
        data = [pd.Series(rng.normal(size=90), index=range(1900, 1990)) for _ in range(4)]
        result = granger_family(*data)
        self.assertEqual(len(result), 30)
        self.assertEqual(result.direction.nunique(), 6)
        np.testing.assert_allclose(result.q, bh_adjust(result.p))
        self.assertTrue((result.q >= result.p).all())

    def test_infeasible_granger_retains_planned_family_without_significance(self):
        s = pd.Series(np.zeros(90), index=range(1900, 1990))
        result = granger_family(s, s, s, s)
        self.assertEqual(len(result), 30)
        self.assertTrue(result.p.isna().all())
        self.assertFalse(result.fdr_significant.any())

    def test_chain_search_p_is_at_least_pointwise_p(self):
        rng = np.random.default_rng(241)
        x = rng.normal(size=80)
        y = np.r_[rng.normal(size=2), x[:-2]] + rng.normal(0, .1, 80)
        frame = lag_correlation_bootstrap(pd.Series(x, index=range(1940, 2020)),
                                         pd.Series(y, index=range(1940, 2020)),
                                         [-2, 0, 2, 4], "", "", n_boot=60)
        self.assertEqual(frame.loc[frame.r.abs().idxmax(), "lag"], 2)
        self.assertTrue((frame.p_lag_search >= frame.p).all())
        self.assertTrue((frame.n_shifts == 79).all())

    def test_baseline_cannot_look_into_future(self):
        s = pd.Series(np.arange(36), index=range(1985, 2021))
        original = baseline_z_score(s)
        later = pd.concat([s, pd.Series([1e6], index=[2021])])
        pd.testing.assert_series_equal(original, baseline_z_score(later).loc[s.index])

    def test_composite_rejects_missing_member_and_excludes_m8_vote(self):
        years = range(1985, 2021)
        s = pd.Series(np.arange(36), index=years, dtype=float)
        members = [("M>=7 quakes", s), ("M>=8 quakes", s * -1),
                   ("X1+ flares", s), ("Pandemic deaths", s)]
        _, _, original = domain_composite(members, years)
        self.assertEqual(original.required_domains.iloc[0], 3)
        np.testing.assert_allclose(original.composite, baseline_z_score(s))
        missing = s.copy(); missing.loc[2015] = np.nan
        _, _, changed = domain_composite([members[0], members[1], ("X1+ flares", missing), members[3]], years)
        self.assertFalse(changed.loc[2015, "eligible"])
        self.assertTrue(np.isnan(changed.loc[2015, "composite"]))

    def test_missing_year_breaks_contraction_and_last_run_is_closed(self):
        s = pd.Series([1., 1., np.nan, 1., 1., 1.], index=range(2000, 2006))
        runs = find_contractions(s, min_duration=3)
        self.assertEqual([(r["start"], r["end"]) for r in runs], [(2003, 2005)])
        self.assertEqual(find_contractions(pd.Series([1.], index=[2020]), min_duration=1)[0]["duration"], 1)

    def test_geomagnetic_day_counts_require_complete_daily_exposure(self):
        dates = pd.date_range("2020-01-01", "2020-12-31")
        frame = pd.DataFrame({"date_iso": dates.strftime("%Y-%m-%d"), "year": 2020,
                              **{f"kp{i}": 0.0 for i in range(1, 9)}})
        frame.loc[0, "kp1"] = 7
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spaceweather.sqlite"
            with sqlite3.connect(path) as con:
                frame.to_sql("gfz_daily", con, index=False)
            con.close()
            self.assertEqual(load_g3_days(path, 2020, 2020).loc[2020], 1)
            with sqlite3.connect(path) as con:
                con.execute("UPDATE gfz_daily SET kp2=NULL WHERE date_iso='2020-01-02'")
            con.close()
            self.assertTrue(np.isnan(load_g3_days(path, 2020, 2020).loc[2020]))

    def test_spectral_null_retains_persistence_and_detects_reference_cycle(self):
        rng = np.random.default_rng(82)
        x = np.zeros(200)
        for i in range(1, 200):
            x[i] = .9 * x[i-1] + rng.normal()
        powers, phi = red_noise_surrogates(x, n_boot=100)
        self.assertGreater(phi, .7)
        self.assertEqual(powers.shape, (100, 101))
        cycle = np.sin(2 * np.pi * np.arange(200) / 11)
        result = spectral_inference(cycle, n_boot=150)
        self.assertLess(result["band_p"], .05)
        self.assertAlmostEqual(result["peak_period"], 11.11, places=1)
        with self.assertRaises(ValueError):
            raw_periodogram([1, 2, np.nan, 4, 5])


if __name__ == "__main__":
    unittest.main()
