"""Audit evidence must preserve source rows and the existing canonical policy."""
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

import flood_linkage_audit as audit
from correlate_events import load_canonical_flood_events


def row(source_id, source='EM-DAT', group=1, start='2000-01-01', end='2000-01-10', deaths=100):
    return dict(source=source, source_id=source_id, match_group_id=group, country='Example',
                iso='AAA', start_date=start, end_date=end, deaths=deaths, cause='Flood')


class FloodLinkageAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'floods.csv'

    def run_audit(self, rows):
        pd.DataFrame(rows).to_csv(self.source, index=False)
        return audit.audit_catalog(self.source)

    def test_different_emdat_events_and_dfo_events_are_flagged_with_all_evidence(self):
        frames, meta = self.run_audit([row('2000-0001-AAA'), row('2000-0002-AAA'),
                                       row('11', 'DFO'), row('12', 'DFO')])
        group = frames['groups'].iloc[0]
        self.assertEqual(set(group.review_flags.split(';')), {'multiple_emdat_event_ids', 'multiple_dfo_event_ids'})
        self.assertEqual(len(frames['quarantine_rows']), 4)
        self.assertEqual(json.loads(group.source_record_numbers), [1, 2, 3, 4])
        self.assertEqual(meta['counts']['canonical_events'], 1)
        self.assertEqual(meta['counts']['unflagged_sensitivity_events'], 0)

    def test_multinational_same_emdat_identity_alone_does_not_prove_mismatch(self):
        frames, _ = self.run_audit([row('2000-0001-AAA'), row('2000-0001-BBB'), row('11', 'DFO')])
        self.assertFalse(frames['groups'].iloc[0].review_required)
        self.assertEqual(len(frames['canonical_unflagged_sensitivity']), 1)

    def test_dates_and_reused_ids_require_review_in_every_affected_group(self):
        frames, meta = self.run_audit([
            row('repeat', 'DFO', 1), row('2000-0001-AAA', group=1, start='2000-02-01', end='2000-02-02'),
            row('repeat', 'DFO', 2), row('2000-0002-AAA', group=2, start='2000-02-03', end='2000-02-01'),
        ])
        groups = frames['groups']
        self.assertTrue(groups['review_flags'].str.contains('source_identity_in_multiple_groups').all())
        self.assertEqual(meta['rule_counts']['incompatible_date_intervals'], 1)
        self.assertEqual(meta['rule_counts']['invalid_date_interval'], 1)

    def test_mortality_disagreement_does_not_change_source_priority_or_invent_totals(self):
        frames, meta = self.run_audit([row('2000-0001-AAA', deaths=100), row('11', 'DFO', deaths=2000)])
        group = frames['groups'].iloc[0]
        self.assertTrue(group.reported_tolls_straddle_1000)
        self.assertTrue(group.selected_below_1000_other_report_at_least_1000)
        self.assertEqual(group.selected_deaths, 100)
        self.assertFalse(group.review_required)
        expected = load_canonical_flood_events(str(self.source))
        actual = frames['canonical_events'].drop(columns=['review_required', 'review_flags'])
        pd.testing.assert_frame_equal(actual, expected.sort_values('canonical_event_id').reset_index(drop=True))

    def test_missing_and_imprecise_dates_exposed_without_manufacturing_dates(self):
        frames, meta = self.run_audit([row('2000-0001-AAA', group=None, start='2000', end='2000'),
                                      row('2000-0002-AAA', group=None, start=None, end=None)])
        self.assertEqual(meta['rule_counts']['imprecise_start_date'], 2)
        self.assertEqual(meta['rule_counts']['missing_start_date'], 1)
        self.assertEqual(frames['quarantine_rows']['start_date'].isna().sum(), 1)

    def test_repeated_write_is_byte_stable_preserves_input_and_output_mtime(self):
        self.run_audit([row('2000-0001-AAA'), row('2000-0002-AAA')])
        before = self.source.read_bytes()
        output = self.root / 'audit'
        first = audit.write_audit(self.source, output)
        times = {p.name: p.stat().st_mtime_ns for p in output.iterdir()}
        second = audit.write_audit(self.source, output)
        self.assertEqual(first, second)
        self.assertEqual(times, {p.name: p.stat().st_mtime_ns for p in output.iterdir()})
        self.assertEqual(before, self.source.read_bytes())
        manifest = json.loads((output / 'manifest.json').read_text())
        self.assertEqual(manifest['source_sha256'], audit.file_digest(self.source))
        for name, digest in manifest['output_sha256'].items():
            self.assertEqual(audit.file_digest(output / name), digest)


if __name__ == '__main__':
    unittest.main()
