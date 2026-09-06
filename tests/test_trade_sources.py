"""PortWatch pagination, source contracts, missingness, and immutable replay."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from monitoring import trade_sources as T


def record(day, portid='chokepoint1', oid=1, volume=100):
    stamp = pd.Timestamp(day)
    row = dict(date=day, year=stamp.year, month=stamp.month, day=stamp.day,
               portid=portid, portname=T.CHOKEPOINTS[portid][0], ObjectId=oid)
    row.update({field: 1 for field in T.COUNT_FIELDS})
    row.update(n_cargo=4, n_total=5)
    row.update({field: 20 for field in T.CAPACITY_FIELDS})
    row.update(capacity_cargo=80, capacity=volume)
    return row


def rows():
    return [record(f'2019-01-0{day}', portid, oid=i*3+day)
            for i, portid in enumerate(T.CHOKEPOINTS) for day in (1, 2, 3)]


class FixtureClient:
    def __init__(self, data=None, corrupt=None, edit=100, fetched='2019-01-12T12:00:00+00:00'):
        self.data = deepcopy(rows() if data is None else data)
        self.corrupt = corrupt
        self.edit = edit
        self.fetched = fetched
        self.requests = []
        self.occurrences = {}

    def get(self, url, params):
        if url == T.ITEM_URL:
            kind = 'item'
            payload = dict(id=T.ITEM_ID, owner=T.ITEM_OWNER, url=T.SERVICE,
                           title='Daily_Chokepoints_Data', modified=90)
        elif url == T.SERVICE:
            kind = 'service'; payload = {'serviceItemId': T.ITEM_ID}
        elif url == T.LAYER:
            kind = 'layer'
            types = {field: 'esriFieldTypeInteger' for field in T.COUNT_FIELDS+T.CAPACITY_FIELDS+['year', 'month', 'day']}
            types.update(date='esriFieldTypeDateOnly', portid='esriFieldTypeString', portname='esriFieldTypeString', ObjectId='esriFieldTypeOID')
            payload = {'objectIdField': 'ObjectId', 'fields': [{'name': k, 'type': v} for k, v in types.items()],
                       'maxRecordCount': 2, 'advancedQueryCapabilities': {'supportsPagination': True},
                       'editingInfo': {'lastEditDate': self.edit}}
        elif params.get('returnCountOnly'):
            kind = 'count'; payload = {'count': len(self.data)}
        elif params.get('returnIdsOnly'):
            kind = 'ids'; payload = {'objectIdFieldName': 'ObjectId', 'objectIds': [r['ObjectId'] for r in self.data]}
        else:
            offset = params['resultOffset']; count = params['resultRecordCount']
            kind = 'page_'+str(offset)
            selected = sorted(self.data, key=lambda row: row['ObjectId'])[offset:offset+count]
            payload = {'features': [{'attributes': row} for row in selected],
                       'exceededTransferLimit': offset+count < len(self.data)}
        occurrence = self.occurrences.get(kind, 0)+1
        self.occurrences[kind] = occurrence
        if self.corrupt:
            payload = self.corrupt(kind, occurrence, deepcopy(payload))
        content = json.dumps(payload).encode()
        self.requests.append({'url': url, 'params': params, 'fetched_at': self.fetched,
                              'sha256': T.digest(content)})
        return content


class PortWatchSourceContract(unittest.TestCase):
    def test_complete_pages_match_independent_id_census_and_exact_fixed_scope(self):
        client = FixtureClient()
        data, source, archive = T.capture(client, T.cutoff('2019-01-12'))
        self.assertEqual(len(data), 9)
        self.assertEqual(source['record_count'], 9)
        self.assertEqual(source['owner'], T.ITEM_OWNER)
        self.assertIn("portid IN ('chokepoint1','chokepoint4','chokepoint6')", source['query_where'])
        self.assertIn("date >= DATE '2019-01-01'", source['query_where'])
        self.assertIn("date <= DATE '2019-01-12'", source['query_where'])
        self.assertEqual([r['name'] for r in archive if r['name'].startswith('page_')],
                         ['page_0', 'page_2', 'page_4', 'page_6', 'page_8'])
        self.assertEqual(T._replay(archive, T.cutoff('2019-01-12')), (data, source))

    def test_failed_short_repeated_extra_and_inconsistent_census_responses_fail(self):
        def mutate(target, transform):
            return lambda kind, occurrence, payload: transform(payload) if kind == target else payload
        cases = [
            ('short page', mutate('page_2', lambda p: dict(p, features=p['features'][:1]))),
            ('repeated ID', mutate('page_2', lambda p: {'features': [{'attributes': r} for r in rows()[:2]]})),
            ('count mismatch', mutate('count', lambda p: {'count': p['count']+1})),
            ('truncated census', mutate('ids', lambda p: dict(p, exceededTransferLimit=True))),
            ('unfinished final page', mutate('page_8', lambda p: dict(p, exceededTransferLimit=True))),
            ('API error', mutate('page_0', lambda p: {'error': {'code': 500, 'message': 'upstream failed'}})),
            ('missing row field', mutate('page_0', lambda p: {'features': [{'attributes': {k: v for k, v in f['attributes'].items() if k != 'capacity'}} for f in p['features']]})),
        ]
        for name, corrupt in cases:
            with self.subTest(name=name), self.assertRaises(ValueError):
                T.capture(FixtureClient(corrupt=corrupt), T.cutoff('2019-01-12'))

    def test_source_edit_or_advertised_ids_change_during_fetch_fails(self):
        for target in ['layer', 'ids', 'count']:
            def corrupt(kind, occurrence, payload):
                if kind == target and occurrence == 2:
                    if target == 'layer': payload['editingInfo']['lastEditDate'] += 1
                    if target == 'ids': payload['objectIds'][-1] = 1000
                    if target == 'count': payload['count'] += 1
                return payload
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'changed during'):
                T.capture(FixtureClient(corrupt=corrupt), T.cutoff('2019-01-12'))

    def test_publisher_repointing_and_changed_date_schema_fail(self):
        for target in ['item', 'service', 'layer']:
            def corrupt(kind, occurrence, payload):
                if kind == target:
                    if target == 'item': payload['owner'] = 'unverified-publisher'
                    if target == 'service': payload['serviceItemId'] = 'new-item'
                    if target == 'layer':
                        next(f for f in payload['fields'] if f['name'] == 'date')['type'] = 'esriFieldTypeString'
                return payload
            with self.subTest(target=target), self.assertRaises(ValueError):
                T.capture(FixtureClient(corrupt=corrupt), T.cutoff('2019-01-12'))

    def test_empty_complete_query_is_failure_not_a_zero_catalog(self):
        with self.assertRaisesRegex(ValueError, 'Empty or inconsistent'):
            T.capture(FixtureClient(data=[]), T.cutoff('2019-01-12'))


class PortWatchDailyCalendar(unittest.TestCase):
    def build(self, data, as_of='2019-01-12'):
        return T.build_tables(data, as_of=as_of, fetched_at='2026-09-06T00:00:00Z', source_version='fixture')

    def test_missing_whole_route_and_interior_days_are_explicit_no_zero_filling(self):
        data = [record('2019-01-01'), record('2019-01-03', oid=2)]
        tables = self.build(data)
        daily = tables['daily.csv']
        self.assertEqual(len(daily), 36)
        self.assertEqual(set(daily.chokepoint), set(v[1] for v in T.CHOKEPOINTS.values()))
        absent = daily[daily.portid.eq('chokepoint6')]
        self.assertTrue(absent.capacity.isna().all())
        self.assertTrue(absent.status.eq('missing_day').all())
        self.assertFalse(absent.usable.any())
        interior = daily[daily.portid.eq('chokepoint1') & daily.date.eq('2019-01-02')].iloc[0]
        self.assertTrue(pd.isna(interior.capacity))
        self.assertFalse(interior.source_observed)
        coverage = tables['coverage.csv'].set_index('portid')
        self.assertEqual(coverage.loc['chokepoint6', 'status'], 'no source observations')
        self.assertEqual(coverage.loc['chokepoint1', 'missing_days'], 10)

    def test_true_zero_valid_null_missing_and_no_commodity_or_country_inference(self):
        data = [record('2019-01-01', volume=0), record('2019-01-02', oid=2, volume=None)]
        daily = self.build(data)['daily.csv'].query("portid == 'chokepoint1'")
        self.assertEqual(daily.iloc[0].capacity, 0)
        self.assertTrue(daily.iloc[0].usable)
        self.assertEqual(daily.iloc[1].status, 'missing_transit_volume')
        self.assertFalse(daily.iloc[1].usable)
        self.assertTrue(daily.provisional.all())
        self.assertTrue(daily.unit.eq('estimated_metric_tons').all())
        self.assertNotIn('country', daily.columns)
        self.assertNotIn('grain', daily.columns)

    def test_whole_utc_day_plus_seven_elapsed_days_and_leap_calendar(self):
        data = [record('2020-02-29')]
        early = self.build(data, '2020-03-07T23:59:59Z')['daily.csv']
        row = early[early.portid.eq('chokepoint1') & early.date.eq('2020-02-29')].iloc[0]
        self.assertTrue(row.day_complete)
        self.assertFalse(row.reporting_lag_elapsed)
        self.assertEqual(row.status, 'reporting_lag')
        self.assertTrue(self.build(data, '2020-03-07T23:59:59Z')['coverage.csv'].latest_expected_eligible_date.eq('2020-02-28').all())
        ready = self.build(data, '2020-03-07')['daily.csv']
        self.assertTrue(ready[ready.portid.eq('chokepoint1') & ready.date.eq('2020-02-29')].iloc[0].usable)
        self.assertTrue(self.build(data, '2020-03-07')['coverage.csv'].latest_expected_eligible_date.eq('2020-02-29').all())
        self.assertEqual(len(ready[ready.portid.eq('chokepoint1') & ready.date.str.startswith('2020-02')]), 29)
        partial = self.build([record('2019-01-12')], '2019-01-12T12:00:00Z')['daily.csv']
        self.assertEqual(partial[partial.source_observed].iloc[0].status, 'calendar_day_not_complete')

    def test_invalid_date_identity_duplicate_negative_and_fractional_counts_fail(self):
        changes = [{'portname': 'Different route'}, {'portid': 'chokepoint99'},
                   {'date': '2019-01-01T00:00:00Z'}, {'month': 2}, {'date': '2018-12-31'},
                   {'capacity': -1}, {'n_total': 2.5}, {'capacity': float('inf')}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.build([record('2019-01-01') | change])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.build([record('2019-01-01'), record('2019-01-01', oid=2)])


class PortWatchActivation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = T.refresh(self.root, client=FixtureClient(), as_of='2019-01-12')
        self.pointer = (self.root/'manifest.json').read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def assert_preserved(self):
        self.assertEqual((self.root/'manifest.json').read_bytes(), self.pointer)
        T.load_snapshot(self.root, replay=True)

    def test_offline_replay_uses_only_immutable_archive_and_preserves_dates(self):
        with patch.object(T, 'Client', side_effect=AssertionError('Offline attempted network')):
            replayed = T.refresh(self.root, offline=True)
        self.assertEqual(replayed, self.manifest)
        self.assert_preserved()
        with self.assertRaisesRegex(ValueError, 'original snapshot cutoff'):
            T.refresh(self.root, offline=True, as_of='2019-01-13')
        self.assert_preserved()

    def test_repeated_identical_capture_is_idempotent_and_revision_creates_new_snapshot(self):
        same = T.refresh(self.root, client=FixtureClient(), as_of='2019-01-12')
        self.assertEqual(same, self.manifest)
        revised = rows(); revised[0]['capacity'] = 120
        manifest = T.refresh(self.root, client=FixtureClient(revised, edit=101), as_of='2019-01-12')
        self.assertNotEqual(manifest['snapshot_id'], self.manifest['snapshot_id'])
        self.assertEqual(manifest['previous_snapshot_id'], self.manifest['snapshot_id'])
        old_path = self.root/'snapshots'/self.manifest['snapshot_id']/'manifest.json'
        old, _ = T.load_snapshot(self.root, manifest_path=old_path, replay=True)
        current, _ = T.load_snapshot(self.root, replay=True)
        self.assertEqual(old['daily.csv'].iloc[0].capacity, 100)
        self.assertEqual(current['daily.csv'].iloc[0].capacity, 120)

    def test_failed_query_missing_history_or_regressed_cutoff_cannot_replace_active(self):
        cases = [FixtureClient(rows()[:-1]), FixtureClient(edit=99),
                 FixtureClient(corrupt=lambda kind, n, payload: {'error': {'code': 500}} if kind == 'page_0' else payload)]
        for client in cases:
            with self.subTest(client=client), self.assertRaises(ValueError):
                T.refresh(self.root, client=client, as_of='2019-01-12')
            self.assert_preserved()
        with self.assertRaisesRegex(ValueError, 'cutoff regressed'):
            T.refresh(self.root, client=FixtureClient(), as_of='2019-01-11')
        self.assert_preserved()

    def test_null_revision_cannot_erase_previously_usable_volume(self):
        revised = rows(); revised[0]['capacity'] = None
        with self.assertRaisesRegex(ValueError, 'history lost usable'):
            T.refresh(self.root, client=FixtureClient(revised), as_of='2019-01-12')
        self.assert_preserved()

    def test_raw_and_normalized_artifact_hashes_are_verified(self):
        for relative in [self.manifest['inputs'][0]['path'], self.manifest['outputs']['daily.csv']['path']]:
            path = self.root/relative; content = path.read_bytes()
            path.write_bytes(b'corrupted')
            try:
                with self.assertRaises((ValueError, OSError)):
                    T.load_snapshot(self.root, replay=True)
            finally:
                path.write_bytes(content)
            self.assert_preserved()


if __name__ == '__main__':
    unittest.main()
