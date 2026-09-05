"""Regression checks for owned-path, content-based, atomic feeder snapshots."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sync_feeders as sf


class FeederSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.repo=self.root/'correlations'
        self.source=self.root/'volcanic-eruptions'/'volcanoes.csv'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('year,vei\n1991,6\n')
        self.feeds=(sf.Feed('volcanic-eruptions','volcanoes.csv','data/volcanoes.csv',columns=('year','vei')),)
        self.target=self.repo/'data/volcanoes.csv'

    def run_sync(self, **kwargs):
        return sf.sync(self.repo,self.root,feeds=self.feeds,**kwargs)

    def test_check_detects_drift_without_creating_any_output(self):
        report=self.run_sync(check=True)
        self.assertFalse(report['ok'])
        self.assertEqual(report['drift'],1)
        self.assertFalse(self.repo.exists())
        self.assertEqual(self.source.read_text(),'year,vei\n1991,6\n')

    def test_second_sync_has_no_byte_or_mtime_churn(self):
        first=self.run_sync()
        self.assertTrue(first['ok']);self.assertEqual(first['changed'],1)
        manifest=self.repo/sf.MANIFEST
        stamps=(self.target.stat().st_mtime_ns,manifest.stat().st_mtime_ns)
        second=self.run_sync()
        self.assertEqual(second['changed'],0)
        self.assertFalse(second['manifest_changed'])
        self.assertEqual(stamps,(self.target.stat().st_mtime_ns,manifest.stat().st_mtime_ns))
        self.assertTrue(self.run_sync(check=True)['ok'])

    def test_same_row_count_revision_detected_by_hash(self):
        self.run_sync()
        old=self.target.read_bytes()
        self.source.write_text('year,vei\n1991,5\n')
        check=self.run_sync(check=True)
        self.assertFalse(check['ok'])
        self.assertNotEqual(check['files'][0]['source_sha256'],check['files'][0]['target_sha256'])
        self.assertEqual(self.target.read_bytes(),old)
        report=self.run_sync()
        self.assertEqual(report['changed'],1)
        self.assertEqual(self.target.read_bytes(),self.source.read_bytes())

    def test_missing_required_source_preflight_preserves_all_existing_outputs(self):
        self.run_sync();before=self.target.read_bytes()
        self.source.write_text('year,vei\n2022,5\n')
        self.feeds += (sf.Feed('missing-repo','source.csv','data/missing.csv'),)
        report=self.run_sync()
        self.assertFalse(report['ok'])
        self.assertEqual(report['changed'],0)
        self.assertEqual(self.target.read_bytes(),before)

    def test_explicit_coverage_sidecar_copied_and_updates_independently(self):
        sidecar=Path(str(self.source)+'.coverage.json')
        sidecar.write_text('{"start_year":1900,"end_year":2022}')
        first=self.run_sync();self.assertEqual(first['changed'],2)
        target_sidecar=Path(str(self.target)+'.coverage.json')
        self.assertEqual(target_sidecar.read_bytes(),sidecar.read_bytes())
        stamp=self.target.stat().st_mtime_ns
        sidecar.write_text('{"start_year":1900,"end_year":2023}')
        second=self.run_sync();self.assertEqual(second['changed'],1)
        self.assertEqual(self.target.stat().st_mtime_ns,stamp)
        self.assertTrue(self.run_sync(check=True)['ok'])

    def test_vanished_sidecar_cannot_silently_leave_stale_coverage(self):
        sidecar=Path(str(self.source)+'.coverage.json')
        sidecar.write_text('{"start_year":1900,"end_year":2022}')
        self.run_sync();sidecar.unlink()
        self.source.write_text('year,vei\n2023,6\n')
        before=self.target.read_bytes()
        report=self.run_sync()
        self.assertFalse(report['ok'])
        self.assertEqual(self.target.read_bytes(),before)
        self.assertTrue(Path(str(self.target)+'.coverage.json').exists())

    def test_protected_central_catalogue_not_overwritten(self):
        protected=self.repo/'data/floods.csv'
        protected.parent.mkdir(parents=True)
        protected.write_text('central-owned\n')
        self.feeds=(sf.Feed('volcanic-eruptions','volcanoes.csv','data/floods.csv'),)
        report=self.run_sync()
        self.assertFalse(report['ok'])
        self.assertEqual(protected.read_text(),'central-owned\n')

    def test_bad_schema_does_not_replace_known_good_snapshot(self):
        self.run_sync();before=self.target.read_bytes()
        self.source.write_text('error,message\n503,unavailable\n')
        report=self.run_sync()
        self.assertFalse(report['ok'])
        self.assertEqual(self.target.read_bytes(),before)

    def test_failed_atomic_replace_preserves_original_and_removes_temp(self):
        self.run_sync();before=self.target.read_bytes()
        self.source.write_text('year,vei\n2022,5\n')
        with patch.object(Path,'replace',side_effect=OSError('simulated rename failure')):
            with self.assertRaises(OSError):
                self.run_sync()
        self.assertEqual(self.target.read_bytes(),before)
        self.assertEqual(list(self.target.parent.glob('.volcanoes.csv.*')),[])


if __name__ == '__main__':
    unittest.main()
