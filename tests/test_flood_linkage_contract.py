"""Reviewed corrections cannot silently survive stale evidence or lose raw rows."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import correlate_events as loaders
import flood_linkage_contract as linkage


class FloodLinkageContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'floods.csv'
        self.sidecar = Path(str(self.path) + '.linkage.json')
        rows = [dict(source='EM-DAT', source_id='2000-0001-AAA', country='Example',
                     start_date='2000-01-01', end_date='2000-01-03', deaths=10, match_group_id=3),
                dict(source='EM-DAT', source_id='2000-0002-AAA', country='Example',
                     start_date='2000-01-10', end_date='2000-01-13', deaths=2000, match_group_id=3),
                dict(source='DFO', source_id='DFO-11', country='Example',
                     start_date='2000-01-10', end_date='2000-01-12', deaths=2100, match_group_id=3),
                dict(source='DFO', source_id='DFO-untouched', country='Elsewhere',
                     start_date='2000-03-01', end_date='2000-03-03', deaths=1, match_group_id=4)]
        pd.DataFrame(rows).to_csv(self.path, index=False)
        raw = list(csv.DictReader(io.StringIO(self.path.read_text())))
        evidence = self.root / 'publisher.csv'
        evidence.write_text('emdat_id,emdat_event_id,dfo_id,status\n2000-0002-AAA,2000-0002,DFO-11,accepted\n')
        self.contract = dict(schema_version=1, catalog_sha256=linkage._digest(self.path.read_bytes()), raw_rows=4,
                             publisher_workbook_sha256='0' * 64,
                             publisher_link_ledger='publisher.csv',
                             evidence_sha256={'publisher.csv': linkage._digest(evidence.read_bytes())},
                             counts=dict(corrected_legacy_groups=1, corrected_source_rows=3,
                                         accepted_publisher_links=1, rejected_publisher_links=0),
                             corrections=[dict(legacy_match_group_id='3.0', method='publisher_id_and_temporal_separation', records=[
                                 dict(source=row['source'], source_id=row['source_id'], row_sha256=linkage._row_digest(row),
                                      canonical_event_id='split:3.0:emdat:' + ('2000-0001' if row['source_id'] == '2000-0001-AAA' else '2000-0002'))
                                 for row in raw[:3]])])
        self.write_contract()

    def write_contract(self):
        self.sidecar.write_text(json.dumps(self.contract))

    def test_reviewed_split_precedes_annual_and_exact_date_thresholds(self):
        before = self.path.read_bytes()
        legacy = loaders.load_canonical_flood_events(str(self.path), apply_linkage_corrections=False)
        corrected = loaders.load_canonical_flood_events(str(self.path))
        self.assertEqual((len(legacy), len(corrected)), (2, 3))
        self.assertEqual(corrected.loc[corrected.source_id.eq('2000-0002-AAA'), 'deaths'].iloc[0], 2000)
        meta = dict(start_year=2000, end_year=2000, complete_through_year=2000)
        annual = loaders.load_yearly_flood_events(str(self.path), 2000, 2000, 1000, coverage=meta)
        exact = loaders.load_flood_event_dates(str(self.path), 1000, exclude_tsunami=False)
        self.assertEqual(annual.iloc[0], 1)
        self.assertEqual(exact, [pd.Timestamp('2000-01-10')])
        self.assertEqual(before, self.path.read_bytes())
        raw = pd.read_csv(self.path)
        identities, metadata = linkage.canonical_identities(raw, self.path)
        self.assertEqual(len(identities), len(raw))
        self.assertEqual(identities.iloc[-1], linkage.legacy_identities(raw).iloc[-1])
        self.assertEqual(metadata['corrected_source_rows'], 3)

    def test_source_hash_change_fails_before_any_correction(self):
        self.path.write_text(self.path.read_text().replace('2000-01-13', '2000-01-14'))
        with self.assertRaisesRegex(ValueError, 'source hash changed'):
            loaders.load_canonical_flood_events(str(self.path))

    def test_stable_record_hash_detects_change_even_if_catalog_hash_is_edited(self):
        self.path.write_text(self.path.read_text().replace('2000-01-13', '2000-01-14'))
        self.contract['catalog_sha256'] = linkage._digest(self.path.read_bytes())
        self.write_contract()
        with self.assertRaisesRegex(ValueError, 'stable source record changed'):
            loaders.load_canonical_flood_events(str(self.path))

    def test_missing_or_changed_publisher_evidence_is_visible_failure(self):
        (self.root / 'publisher.csv').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'evidence missing or hash mismatch'):
            loaders.load_canonical_flood_events(str(self.path))
        (self.root / 'publisher.csv').unlink()
        with self.assertRaisesRegex(ValueError, 'evidence missing or hash mismatch'):
            loaders.load_canonical_flood_events(str(self.path))

    def test_managed_catalog_requires_ledger_but_explicit_legacy_baseline_remains_available(self):
        self.sidecar.unlink()
        with patch.object(linkage, 'MANAGED_CATALOG', self.path):
            with self.assertRaisesRegex(ValueError, 'contract missing'):
                loaders.load_canonical_flood_events(str(self.path))
            self.assertEqual(len(loaders.load_canonical_flood_events(str(self.path), apply_linkage_corrections=False)), 2)

    def test_correction_cannot_drop_members_or_merge_a_different_legacy_group(self):
        original = json.loads(json.dumps(self.contract))
        self.contract['corrections'][0]['records'].pop()
        self.write_contract()
        with self.assertRaisesRegex(ValueError, 'preserve every member'):
            loaders.load_canonical_flood_events(str(self.path))
        self.contract = original
        self.contract['corrections'][0]['records'][0]['canonical_event_id'] = 'split:4.0:emdat:2000-0001'
        self.write_contract()
        with self.assertRaisesRegex(ValueError, 'within its reviewed legacy group'):
            loaders.load_canonical_flood_events(str(self.path))

    def test_unknown_mortality_remains_unknown_after_split(self):
        self.path.write_text(self.path.read_text().replace(',2000-01-13,2000,', ',2000-01-13,,'))
        raw = list(csv.DictReader(io.StringIO(self.path.read_text())))
        self.contract['catalog_sha256'] = linkage._digest(self.path.read_bytes())
        for row in self.contract['corrections'][0]['records']:
            row['row_sha256'] = linkage._row_digest(next(item for item in raw if item['source_id'] == row['source_id']))
        self.write_contract()
        result = loaders.load_yearly_flood_deaths(str(self.path), 2000, 2000,
                                                  coverage=dict(start_year=2000, end_year=2000, complete_through_year=2000))
        self.assertTrue(pd.isna(result.iloc[0]))

    def test_dfo_assignment_cannot_contradict_accepted_publisher_reference(self):
        self.contract['corrections'][0]['records'][2]['canonical_event_id'] = 'split:3.0:emdat:2000-0001'
        self.write_contract()
        with self.assertRaisesRegex(ValueError, 'contradicts the accepted publisher'):
            loaders.load_canonical_flood_events(str(self.path))

    def test_real_reviewed_source_contract_has_only_eleven_splits_and_preserves_other_blocks(self):
        path = linkage.MANAGED_CATALOG
        raw = pd.read_csv(path)
        previous = linkage.legacy_identities(raw)
        corrected, metadata = linkage.canonical_identities(raw, path)
        self.assertEqual(metadata['corrected_groups'], 11)
        self.assertEqual(metadata['corrected_source_rows'], 35)
        self.assertEqual((previous.nunique(), corrected.nunique()), (7434, 7445))
        self.assertEqual(int(previous.ne(corrected).sum()), 35)
        self.assertEqual({metadata['accepted_publisher_links'], metadata['rejected_publisher_links']}, {231, 40})

    def test_refresh_fingerprints_detect_same_row_count_evidence_revisions(self):
        from source_tracking import collect_fingerprints, changed_groups
        data = self.root / 'data'
        data.mkdir()
        contract = data / 'floods.csv.linkage.json'
        evidence = data / 'publisher.csv'
        contract.write_bytes(self.sidecar.read_bytes())
        evidence.write_text('id,external\none,DFO:1\n')
        before = collect_fingerprints(self.root)
        self.assertIn('data/floods.csv.linkage.json', before)
        self.assertIn('data/publisher.csv', before)
        evidence.write_text('id,external\none,DFO:2\n')
        after = collect_fingerprints(self.root)
        self.assertNotEqual(before['data/publisher.csv'], after['data/publisher.csv'])
        self.assertTrue(changed_groups(before, after)[0])


if __name__ == '__main__':
    unittest.main()
