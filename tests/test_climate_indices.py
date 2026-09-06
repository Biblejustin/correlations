"""Offline climate-source contracts and atomic refresh regression coverage."""
import datetime as dt
import gzip
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from monitoring import climate_indices as C


def payloads():
    months = pd.date_range("2022-12-01", "2025-01-01", freq="MS")
    values = {stamp: round(float(np.sin(i / 4)), 2) for i, stamp in enumerate(months)}
    rni = ["YR MTH ANOM"] + [f"{stamp.year} {stamp.month} {value:.2f}" for stamp, value in values.items()]
    roni = ["SEAS YR ANOM"]
    for center in pd.date_range("2023-01-01", "2024-12-01", freq="MS"):
        window = pd.date_range(center-pd.DateOffset(months=1), periods=3, freq="MS")
        value = np.mean([values[stamp] for stamp in window])
        roni.append(f"{C.SEASONS[center.month-1]} {center.year} {value:.2f}")
    dmi = ["2023 2025"] + [f"{year} " + " ".join(f"{month / 10:.2f}" for month in range(1, 13))
                               for year in range(2023, 2026)] + ["-99.99", "NOAA PSL fixture"]
    return {
        "cpc_definition": b'<table><tr><td><strong>Monthly</strong> Relative ERSSTv6 (1991&ndash;2020 base period) <a href="/data/indices/Rnino34.ascii.txt">Data</a></td></tr><tr><td><strong>Seasonal</strong> Relative ERSSTv6 (1991&ndash;2020 base period) <a href="/data/indices/RONI.ascii.txt">Data</a></td></tr></table>',
        "dmi_definition": b"NOAA PSL HadISST1.1 Dipole Mode Index",
        "rni": ("\n".join(rni) + "\n").encode(),
        "roni": ("\n".join(roni) + "\n").encode(),
        "dmi": ("\n".join(dmi) + "\n").encode(),
    }


class FixtureClient:
    def __init__(self, data=None, fail=None):
        self.data = data if data is not None else payloads()
        self.fail = fail
        self.requests = []

    def get(self, url):
        key = next(key for key, candidate in C.URLS.items() if url == candidate)
        if key == self.fail:
            raise ConnectionError(f"Fixture source failed: {key}")
        value = self.data[key]
        self.requests.append({"url": url, "fetched_at": "2025-02-01T00:00:00+00:00",
                              "sha256": C.digest(value)})
        return value


class ClimateSourceParsing(unittest.TestCase):
    def test_cpc_declared_sentinels_are_missing_but_unknown_codes_fail(self):
        frame = C.parse_cpc(b"YR MTH ANOM\n2023 1 -99.9\n2023 2 -99.99\n2023 3 -999\n2023 4 -999.9\n")
        self.assertTrue(frame.value.isna().all())
        for code in ["99.99", "NaN", "inf"]:
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, "Invalid climate anomaly"):
                C.parse_cpc(f"YR MTH ANOM\n2023 1 {code}\n".encode())

    def test_duplicate_cpc_periods_fail_for_monthly_and_seasonal(self):
        for seasonal, content in [(False, b"YR MTH ANOM\n2023 1 0.1\n2023 1 0.2\n"),
                                  (True, b"SEAS YR ANOM\nDJF 2023 0.1\nDJF 2023 0.2\n")]:
            with self.subTest(seasonal=seasonal), self.assertRaisesRegex(ValueError, "duplicate"):
                C.parse_cpc(content, seasonal=seasonal)

    def test_dmi_requires_declared_sentinel_and_exact_ordered_year_rows(self):
        data = payloads()["dmi"]
        missing = data.replace(b"2024 0.10", b"2024 -99.99")
        frame = C.parse_dmi(missing)
        self.assertTrue(frame[frame.year.eq(2024) & frame.month.eq(1)].value.isna().all())
        invalid = [data.replace(b"-99.99\n", b""), data.replace(b"2024 0.10", b"2023 0.10"),
                   data.replace(b"2024 0.10", b"2024 -88.88")]
        for content in invalid:
            with self.subTest(content=content[:50]), self.assertRaises(ValueError):
                C.parse_dmi(content)

    def test_seasonal_windows_wrap_years_and_preserve_leap_february(self):
        frame = C.parse_cpc(b"SEAS YR ANOM\nDJF 2024 0.1\nNDJ 2024 0.2\n", seasonal=True)
        self.assertEqual(frame.period_start.tolist(), ["2023-12-01", "2024-11-01"])
        self.assertEqual(frame.period_end.tolist(), ["2024-02-29", "2025-01-31"])
        self.assertEqual(frame.year.tolist(), [2024, 2024])

    def test_source_product_and_baseline_changes_fail_before_splicing(self):
        data = payloads()
        C.validate_definitions(data)
        for key, old, new in [("cpc_definition", b"ERSSTv6", b"ERSSTv7"),
                              ("cpc_definition", b"1991&ndash;2020", b"2001&ndash;2030"),
                              ("dmi_definition", b"HadISST1.1", b"HadISST2.0")]:
            changed = {**data, key: data[key].replace(old, new)}
            with self.subTest(key=key, new=new), self.assertRaises(ValueError):
                C.validate_definitions(changed)

    def test_rni_roni_must_have_matching_three_month_values_and_months(self):
        data = payloads()
        lines = data["roni"].decode().splitlines()
        season, year, value = lines[1].split()
        lines[1] = f"{season} {year} {float(value)+.02:.2f}"
        with self.assertRaisesRegex(ValueError, "alignment mismatch"):
            C.build_tables({**data, "roni": "\n".join(lines).encode()}, "2025-02-01")
        rni = data["rni"].decode().splitlines()
        # DJF 2023 requires December 2022, despite its nominal year being 2023.
        removed = "\n".join(line for line in rni if not line.startswith("2022 12 ")).encode()
        with self.assertRaisesRegex(ValueError, "alignment mismatch"):
            C.build_tables({**data, "rni": removed}, "2025-02-01")

    def test_annual_controls_use_complete_january_december_months(self):
        data = payloads()
        tables = C.build_tables(data, "2024-12-31")
        self.assertEqual(tables["annual.csv"].year.tolist(), [2023, 2024])
        monthly_rni = C.parse_cpc(data["rni"])
        expected = monthly_rni[monthly_rni.year.eq(2024)].value.mean()
        self.assertAlmostEqual(tables["annual.csv"].set_index("year").loc[2024, "rni"], expected)
        # NDJ 2024 reaches into January 2025, so remains incomplete even though
        # all 12 monthly values used in the 2024 annual control are available.
        ndj = tables["roni_seasonal.csv"].query("year == 2024 and season == 'NDJ'").iloc[0]
        self.assertFalse(ndj.period_complete)
        self.assertFalse(ndj.usable)
        intraday = C.build_tables(data, dt.datetime(2024, 12, 31, 12, tzinfo=dt.timezone.utc))
        self.assertEqual(intraday["annual.csv"].year.tolist(), [2023])

    def test_missing_month_prevents_annual_mean_and_exposes_coverage(self):
        data = payloads()
        data["dmi"] = data["dmi"].replace(b"2024 0.10", b"2024 -99.99")
        tables = C.build_tables(data, "2025-02-01")
        self.assertEqual(tables["annual.csv"].year.tolist(), [2023])
        coverage = tables["annual_coverage.csv"].query("year == 2024 and index == 'dmi'").iloc[0]
        self.assertEqual(coverage.observed_months, 11)
        self.assertTrue(coverage.year_complete)


class ClimateSnapshotActivation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = C.refresh(self.root, client=FixtureClient(), as_of="2025-02-01")
        self.pointer = (self.root / "manifest.json").read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def assert_active_unchanged(self):
        self.assertEqual((self.root / "manifest.json").read_bytes(), self.pointer)
        _, manifest = C.load_snapshot(self.root)
        self.assertEqual(manifest["snapshot_id"], self.manifest["snapshot_id"])

    def test_successful_snapshot_round_trip_and_raw_hashes(self):
        tables, manifest = C.load_snapshot(self.root)
        self.assertEqual(set(tables), {"monthly.csv", "roni_seasonal.csv", "annual.csv", "annual_coverage.csv"})
        self.assertEqual(tables["annual.csv"].year.tolist(), [2023, 2024])
        for record in manifest["inputs"].values():
            self.assertEqual(C.digest(gzip.decompress((self.root / record["path"]).read_bytes())), record["sha256"])
        C.refresh(self.root, client=FixtureClient(), as_of="2025-02-01")
        self.assert_active_unchanged()

    def test_source_failure_and_lost_historical_year_preserve_active_pointer(self):
        with self.assertRaises(ConnectionError):
            C.refresh(self.root, client=FixtureClient(fail="dmi"), as_of="2025-02-02")
        self.assert_active_unchanged()
        data = payloads()
        lines = data["dmi"].decode().splitlines()
        data["dmi"] = ("\n".join(["2024 2025"] + lines[2:]) + "\n").encode()
        with self.assertRaisesRegex(ValueError, "lost previously observed"):
            C.refresh(self.root, client=FixtureClient(data), as_of="2025-02-02")
        self.assert_active_unchanged()

    def test_failed_vintage_alignment_preserves_active_pointer(self):
        data = payloads()
        data["roni"] = data["roni"].replace(b"DJF 2023 0.24", b"DJF 2023 1.24")
        self.assertNotEqual(data["roni"], payloads()["roni"])
        with self.assertRaisesRegex(ValueError, "alignment mismatch"):
            C.refresh(self.root, client=FixtureClient(data), as_of="2025-02-02")
        self.assert_active_unchanged()

    def test_earlier_cutoff_cannot_activate_a_smaller_annual_panel(self):
        with self.assertRaises(ValueError):
            C.refresh(self.root, client=FixtureClient(), as_of="2024-07-01")
        self.assert_active_unchanged()

    def test_earlier_cutoff_cannot_hide_monthly_values_with_same_annual_panel(self):
        with self.assertRaisesRegex(ValueError, 'activation cutoff regressed'):
            C.refresh(self.root, client=FixtureClient(), as_of='2025-01-15')
        self.assert_active_unchanged()

    def test_derived_output_tampering_and_source_contract_mismatch_fail(self):
        annual = self.root / self.manifest["outputs"]["annual.csv"]["path"]
        annual.write_bytes(annual.read_bytes() + b"2025,0,0\n")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            C.load_snapshot(self.root)
        changed = json.loads(self.pointer)
        changed["versions"]["rni"] = "different source product"
        (self.root / "manifest.json").write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "source contract changed"):
            C.load_snapshot(self.root)

    def test_corrupt_raw_archive_is_not_a_valid_auditable_snapshot(self):
        record = self.manifest["inputs"]["rni"]
        (self.root / record["path"]).write_bytes(gzip.compress(b"changed raw source", mtime=0))
        with self.assertRaises(ValueError):
            C.load_snapshot(self.root)


if __name__ == "__main__":
    unittest.main()
