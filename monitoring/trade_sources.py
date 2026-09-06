"""Immutable IMF PortWatch transit snapshots; AIS estimates are not grain trade.

Source definitions: https://portwatch.imf.org/pages/data-and-methodology and the
IMF-owned ArcGIS item below. Transit volume is estimated vessel payload times
deadweight tonnage. Transit counts have a 48-hour same-vessel counting threshold;
counts across nearby chokepoints must not be treated as independent shipments.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import fcntl
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

import numpy as np
import pandas as pd

from monitoring.feeds import BASE, Client
from source_tracking import write_json_if_changed

ROOT = BASE/'data/trade_shipping'
PLAN_PATH = Path(__file__).with_name('trade_plan.json')
SERVICE = 'https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/Daily_Chokepoints_Data/FeatureServer'
LAYER = SERVICE+'/0'
ITEM_ID = '3da2b9ca97684916b75c4013f95d18ab'
ITEM_URL = 'https://www.arcgis.com/sharing/rest/content/items/'+ITEM_ID
ITEM_OWNER = 'IMF-portwatch_imf_dataviz'
SOURCE_ID = 'imf_portwatch_daily_chokepoints'
START_DATE = '2019-01-01'
REPORTING_LAG_DAYS = 7
CHOKEPOINTS = {
    'chokepoint1': ('Suez Canal', 'Suez Canal'),
    'chokepoint4': ('Bab el-Mandeb Strait', 'Bab el-Mandeb'),
    'chokepoint6': ('Strait of Hormuz', 'Strait of Hormuz'),
}
COUNT_FIELDS = ['n_container', 'n_dry_bulk', 'n_general_cargo', 'n_roro', 'n_tanker', 'n_cargo', 'n_total']
CAPACITY_FIELDS = ['capacity_container', 'capacity_dry_bulk', 'capacity_general_cargo',
                   'capacity_roro', 'capacity_tanker', 'capacity_cargo', 'capacity']
FIELDS = ['date', 'year', 'month', 'day', 'portid', 'portname']+COUNT_FIELDS+CAPACITY_FIELDS+['ObjectId']
OUTPUTS = {'daily.csv', 'coverage.csv'}
LIMITATIONS = [
    'AIS-derived estimated transit volume in metric tons; not measured grain cargo, national imports, customs trade, or bare maximum ship capacity.',
    'Transit counts and class aggregates overlap; never add cargo/total to component classes or treat the three routes as independent shocks.',
    'Calendar rows do not establish complete AIS reception or vessel coverage. Missing records and null values remain unavailable, never zero.',
    'Source publishes preliminary weekly updates (Tuesday 9 AM ET); seven elapsed days is a project exclusion rule, not an IMF stabilization guarantee.',
    'All history can revise after AIS, methodology, or coverage changes. Retained snapshots do not reconstruct release-time historical availability.',
    'No country, commodity, origin/destination, rerouting, price, or causal interpretation can be inferred from these route totals alone.',
]


def digest(content):
    return hashlib.sha256(content).hexdigest()


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()


def cutoff(as_of=None):
    """Aware UTC cutoff; a date-only argument includes that entire UTC date."""
    value = as_of if as_of is not None else dt.datetime.now(dt.timezone.utc)
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError('Missing PortWatch cutoff')
    stamp = stamp.tz_localize('UTC') if stamp.tzinfo is None else stamp.tz_convert('UTC')
    if (isinstance(value, dt.date) and not isinstance(value, dt.datetime)
            or isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)):
        stamp += pd.Timedelta(days=1)
    if stamp <= pd.Timestamp(START_DATE, tz='UTC'):
        raise ValueError('PortWatch cutoff must follow declared source start')
    return stamp


def validate_plan():
    raw = PLAN_PATH.read_bytes()
    plan = json.loads(raw)
    if (plan['chokepoints'] != [value[1] for value in CHOKEPOINTS.values()]
            or plan['shipping_month'] != 'Calendar monthly mean of daily estimated total transit volume, requiring every calendar day and excluding the last seven elapsed days. Never infer zero from missing days. No partial-month extrapolation.'):
        raise ValueError('Frozen shipping source/coverage plan changed; review required')
    return digest(raw)


def _integer(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value or value < minimum:
        raise ValueError(f'Invalid PortWatch {label}')
    return int(value)


def _decode(payload, name):
    try:
        value = json.loads(payload)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'Invalid PortWatch JSON: {name}') from exc
    if not isinstance(value, dict) or 'error' in value:
        raise ValueError(f'PortWatch API error: {name}')
    return value


def _validate_source(item, service, layer):
    if (item.get('id') != ITEM_ID or item.get('owner') != ITEM_OWNER
            or item.get('url') != SERVICE or item.get('title') != 'Daily_Chokepoints_Data'
            or service.get('serviceItemId') != ITEM_ID):
        raise ValueError('PortWatch publisher/item/service binding changed')
    fields = {row['name']: row['type'] for row in layer.get('fields', [])}
    expected = {name: 'esriFieldTypeInteger' for name in COUNT_FIELDS+CAPACITY_FIELDS+['year', 'month', 'day']}
    expected.update(date='esriFieldTypeDateOnly', portid='esriFieldTypeString',
                    portname='esriFieldTypeString', ObjectId='esriFieldTypeOID')
    if (any(fields.get(key) != value for key, value in expected.items())
            or layer.get('objectIdField') != 'ObjectId'
            or not layer.get('advancedQueryCapabilities', {}).get('supportsPagination')):
        raise ValueError('PortWatch daily source schema changed')
    _integer(layer.get('maxRecordCount'), 'page limit', minimum=1)
    _integer(layer.get('editingInfo', {}).get('lastEditDate'), 'source edit marker', minimum=1)


def _ids(value):
    if value.get('objectIdFieldName') != 'ObjectId' or not isinstance(value.get('objectIds'), list):
        raise ValueError('PortWatch ID census missing')
    result = [_integer(v, 'object ID', minimum=1) for v in value['objectIds']]
    if len(set(result)) != len(result):
        raise ValueError('Duplicate PortWatch advertised IDs')
    if value.get('exceededTransferLimit'):
        raise ValueError('Truncated PortWatch ID census')
    return set(result)


def _collect(get, as_of):
    """Same validated request transcript is used for live capture and offline replay."""
    item = get('item', ITEM_URL, {'f': 'json'})
    service = get('service', SERVICE, {'f': 'json'})
    layer = get('layer_before', LAYER, {'f': 'json'})
    _validate_source(item, service, layer)
    last_date = (as_of-pd.Timedelta(nanoseconds=1)).date().isoformat()
    where = "portid IN ('chokepoint1','chokepoint4','chokepoint6') AND date >= DATE '2019-01-01' AND date <= DATE '"+last_date+"'"
    query = {'where': where, 'f': 'json'}
    count = _integer(get('count_before', LAYER+'/query', dict(query, returnCountOnly='true')).get('count'), 'record count')
    ids = _ids(get('ids_before', LAYER+'/query', dict(query, returnIdsOnly='true')))
    if count != len(ids) or not count:
        raise ValueError('Empty or inconsistent PortWatch complete-query census')
    if count > 3*((pd.Timestamp(last_date)-pd.Timestamp(START_DATE)).days+1):
        raise ValueError('PortWatch query exceeds one row per fixed route/day')
    page_size = min(1000, layer['maxRecordCount'])
    rows, observed_ids = [], set()
    for offset in range(0, count, page_size):
        page = get(f'page_{offset}', LAYER+'/query', dict(query, outFields=','.join(FIELDS),
                   returnGeometry='false', orderByFields='ObjectId ASC', resultOffset=offset, resultRecordCount=page_size))
        features = page.get('features')
        if not isinstance(features, list) or len(features) != min(page_size, count-offset):
            raise ValueError('Truncated or malformed PortWatch page')
        if offset+len(features) == count and page.get('exceededTransferLimit'):
            raise ValueError('PortWatch final page remains truncated')
        for feature in features:
            row = feature.get('attributes')
            if not isinstance(row, dict) or not set(FIELDS) <= set(row):
                raise ValueError('PortWatch row missing source fields')
            oid = _integer(row['ObjectId'], 'object ID', minimum=1)
            if oid not in ids or oid in observed_ids:
                raise ValueError('Repeated or out-of-scope PortWatch page IDs')
            observed_ids.add(oid); rows.append(row)
    final_ids = _ids(get('ids_after', LAYER+'/query', dict(query, returnIdsOnly='true')))
    final_count = _integer(get('count_after', LAYER+'/query', dict(query, returnCountOnly='true')).get('count'), 'record count')
    final_layer = get('layer_after', LAYER, {'f': 'json'})
    _validate_source(item, service, final_layer)
    if (observed_ids != ids or final_ids != ids or final_count != count
            or layer.get('editingInfo') != final_layer.get('editingInfo')
            or layer['fields'] != final_layer['fields']):
        raise ValueError('PortWatch source changed during full-history query')
    return rows, {'item_id': ITEM_ID, 'owner': ITEM_OWNER, 'service_url': SERVICE,
                  'query_where': where, 'record_count': count, 'editing_info': layer['editingInfo'],
                  'item_modified': item.get('modified'), 'field_types': {r['name']: r['type'] for r in layer['fields']}}


def capture(client, as_of):
    archive = []
    def get(name, url, params):
        content = client.get(url, params)
        meta = client.requests[-1] if client.requests else {}
        archive.append({'name': name, 'url': url, 'params': params, 'content': content,
                        'fetched_at': meta.get('fetched_at') or dt.datetime.now(dt.timezone.utc).isoformat(),
                        'published_at': meta.get('published_at')})
        return _decode(content, name)
    rows, source = _collect(get, as_of)
    return rows, source, archive


def build_tables(rows, *, as_of, fetched_at, source_version):
    """Keep all fixed routes/dates. A true observed zero remains valid."""
    as_of = cutoff(as_of)
    last = (as_of-pd.Timedelta(nanoseconds=1)).tz_localize(None).normalize()
    first = pd.Timestamp(START_DATE)
    normalized, seen = [], set()
    for raw in rows:
        if raw['portid'] not in CHOKEPOINTS or raw['portname'] != CHOKEPOINTS[raw['portid']][0]:
            raise ValueError('PortWatch fixed route ID/name changed or outside query scope')
        text = raw['date']
        if not isinstance(text, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
            raise ValueError('PortWatch date-only format changed')
        stamp = pd.Timestamp(text)
        if stamp < first or stamp > last or [raw['year'], raw['month'], raw['day']] != [stamp.year, stamp.month, stamp.day]:
            raise ValueError('PortWatch date components or query scope mismatch')
        key = (raw['portid'], text)
        if key in seen:
            raise ValueError('Duplicate PortWatch route/date')
        seen.add(key)
        record = dict(raw)
        for field in COUNT_FIELDS+CAPACITY_FIELDS:
            record[field] = np.nan if raw[field] is None else _integer(raw[field], field)
        normalized.append(record)
    observed = pd.DataFrame(normalized, columns=FIELDS).set_index(['portid', 'date'])
    dates = pd.date_range(first, last, freq='D').strftime('%Y-%m-%d')
    expected = pd.MultiIndex.from_product([CHOKEPOINTS, dates], names=['portid', 'date'])
    daily = observed.reindex(expected).reset_index()
    daily['source_observed'] = daily.ObjectId.notna()
    daily['portname'] = daily.portid.map(lambda p: CHOKEPOINTS[p][0])
    daily['chokepoint'] = daily.portid.map(lambda p: CHOKEPOINTS[p][1])
    stamps = pd.to_datetime(daily.date, utc=True)
    for field in ['year', 'month', 'day']:
        daily[field] = getattr(stamps.dt, field)
    day_ends = stamps+pd.Timedelta(days=1)
    daily['day_complete'] = day_ends <= as_of
    daily['reporting_lag_elapsed'] = day_ends+pd.Timedelta(days=REPORTING_LAG_DAYS) <= as_of
    daily['usable'] = daily.source_observed & daily.capacity.notna() & daily.reporting_lag_elapsed
    daily['status'] = np.select([~daily.source_observed, daily.capacity.isna(), ~daily.day_complete,
                                  ~daily.reporting_lag_elapsed],
                                 ['missing_day', 'missing_transit_volume', 'calendar_day_not_complete', 'reporting_lag'],
                                 default='available')
    daily['source_id'] = SOURCE_ID
    daily['source_version'] = source_version
    daily['source_url'] = LAYER
    daily['fetched_at'] = fetched_at
    daily['unit'] = 'estimated_metric_tons'
    daily['provisional'] = True
    coverage = []
    for portid, group in daily.groupby('portid', sort=False):
        present = group[group.source_observed]
        coverage.append({'portid': portid, 'portname': CHOKEPOINTS[portid][0], 'chokepoint': CHOKEPOINTS[portid][1],
                         'expected_days': len(group), 'source_rows': len(present),
                         'first_source_date': present.date.min() if len(present) else None,
                         'last_source_date': present.date.max() if len(present) else None,
                         'missing_days': int((~group.source_observed).sum()),
                         'null_volume_days': int((group.source_observed & group.capacity.isna()).sum()),
                         'usable_days': int(group.usable.sum()),
                         'latest_expected_eligible_date': ((as_of-pd.Timedelta(days=REPORTING_LAG_DAYS)).normalize()-pd.Timedelta(days=1)).date().isoformat(),
                         'ais_reception_coverage': 'unverified',
                         'status': 'observed route; missing periods retained' if len(present) else 'no source observations'})
    return {'daily.csv': daily, 'coverage.csv': pd.DataFrame(coverage)}


def _path(root, relative):
    path = root/relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('PortWatch archive path escapes snapshot root')
    return path


def _read_archive(root, manifest):
    archive = []
    for record in manifest['inputs']:
        content = gzip.decompress(_path(root, record['path']).read_bytes())
        if digest(content) != record['sha256']:
            raise ValueError('PortWatch raw archive hash mismatch')
        archive.append(dict(record, content=content))
    return archive


def _replay(archive, as_of):
    position = 0
    def get(name, url, params):
        nonlocal position
        if position >= len(archive):
            raise ValueError('Incomplete PortWatch raw request transcript')
        record = archive[position]; position += 1
        if (record['name'], record['url'], record['params']) != (name, url, params):
            raise ValueError('PortWatch archived query scope/order mismatch')
        return _decode(record['content'], name)
    result = _collect(get, as_of)
    if position != len(archive):
        raise ValueError('Unexpected extra PortWatch archive responses')
    return result


def load_snapshot(root=ROOT, *, manifest_path=None, replay=False):
    root = Path(root)
    manifest = json.loads((Path(manifest_path) if manifest_path else root/'manifest.json').read_text())
    if (manifest.get('schema_version') != 1 or manifest.get('source_id') != SOURCE_ID
            or manifest.get('item_id') != ITEM_ID or manifest.get('chokepoints') != {k: list(v) for k, v in CHOKEPOINTS.items()}
            or manifest.get('reporting_lag_days') != REPORTING_LAG_DAYS or manifest.get('start_date') != START_DATE
            or set(manifest.get('outputs', {})) != OUTPUTS):
        raise ValueError('PortWatch snapshot source contract mismatch')
    archive = _read_archive(root, manifest)
    tables = {}
    contents = {}
    for name, record in manifest['outputs'].items():
        content = _path(root, record['path']).read_bytes()
        if digest(content) != record['sha256']:
            raise ValueError('PortWatch normalized output hash mismatch')
        contents[name] = content
        tables[name] = pd.read_csv(_path(root, record['path']))
        if len(tables[name]) != record['rows']:
            raise ValueError('PortWatch output row-count mismatch')
    actual_id = digest(b''.join(name.encode()+contents[name] for name in sorted(contents)))
    if manifest['snapshot_id'] != actual_id:
        raise ValueError('PortWatch snapshot identity mismatch')
    if replay:
        rows, source = _replay(archive, cutoff(manifest['as_of_utc']))
        if source != manifest['source']:
            raise ValueError('PortWatch archived source metadata mismatch')
        rebuilt = build_tables(rows, as_of=manifest['as_of_utc'], fetched_at=manifest['fetched_at'], source_version=manifest['source_version'])
        for name, table in rebuilt.items():
            if table.to_csv(index=False, lineterminator='\n').encode() != contents[name]:
                raise ValueError('PortWatch offline replay differs from activated output')
    return tables, manifest


def _immutable(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError('Immutable PortWatch artifact conflict')
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content); handle.flush(); os.fsync(handle.fileno())
    try:
        try:
            os.link(temporary, path)  # Atomic creation; never overwrite an immutable file.
        except FileExistsError:
            if path.read_bytes() != content:
                raise ValueError('Immutable PortWatch artifact conflict')
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _lock(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root/'.refresh.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('Another PortWatch refresh is running') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def refresh(root=ROOT, *, offline=False, client=None, as_of=None):
    """Capture full history; activate only after census, schema, and archive checks.

    Offline mode replays the existing immutable source transcript without network
    access or advancing its retrieval/reference dates. Historical exports belong
    in separate roots; an active snapshot's cutoff cannot move backwards.
    """
    root = Path(root)
    plan_sha = validate_plan()
    if offline:
        _, manifest = load_snapshot(root, replay=True)
        if as_of is not None and cutoff(as_of) != cutoff(manifest['as_of_utc']):
            raise ValueError('Offline replay must preserve the original snapshot cutoff')
        return manifest
    with _lock(root):
        bound = cutoff(as_of)
        previous = previous_manifest = None
        if (root/'manifest.json').exists():
            previous, previous_manifest = load_snapshot(root)
            if bound < cutoff(previous_manifest['as_of_utc']):
                raise ValueError('PortWatch activation cutoff regressed; use a separate historical output root')
        if client is None:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            client = Client(cache=BASE/'.cache/trade_shipping')
            client.session.mount('https://', HTTPAdapter(max_retries=Retry(total=3, backoff_factor=.75,
                status_forcelist=[429, 500, 502, 503, 504], allowed_methods=['GET'])))
        rows, source, archive = capture(client, bound)
        if previous_manifest and source['editing_info']['lastEditDate'] < previous_manifest['source']['editing_info']['lastEditDate']:
            raise ValueError('PortWatch source vintage regressed; review before activation')
        fetched_at = max(r['fetched_at'] for r in archive)
        version = f'{ITEM_ID}; source edit {source["editing_info"]["lastEditDate"]}'
        tables = build_tables(rows, as_of=bound, fetched_at=fetched_at, source_version=version)
        if previous is not None:
            old, new = previous['daily.csv'], tables['daily.csv']
            for field, label in [('source_observed', 'observed route/dates'), ('usable', 'usable route/dates')]:
                before = set(map(tuple, old.loc[old[field], ['portid', 'date']].to_numpy()))
                after = set(map(tuple, new.loc[new[field], ['portid', 'date']].to_numpy()))
                if not before <= after:
                    raise ValueError(f'PortWatch history lost {label}; review before activation')
        contents = {name: table.to_csv(index=False, lineterminator='\n').encode() for name, table in tables.items()}
        snapshot_id = digest(b''.join(name.encode()+contents[name] for name in sorted(contents)))
        outputs, inputs = {}, []
        for name, content in contents.items():
            relative = f'snapshots/{snapshot_id}/{name}'
            _immutable(root/relative, content)
            outputs[name] = {'path': relative, 'sha256': digest(content), 'rows': len(tables[name])}
        for record in archive:
            content = record['content']; sha = digest(content)
            relative = f'raw/{sha}.json.gz'
            _immutable(root/relative, gzip.compress(content, mtime=0))
            inputs.append({k: v for k, v in record.items() if k != 'content'} | {'path': relative, 'sha256': sha})
        manifest = {'schema_version': 1, 'source_id': SOURCE_ID, 'item_id': ITEM_ID,
                    'source_version': version, 'start_date': START_DATE, 'as_of_utc': bound.isoformat(),
                    'fetched_at': fetched_at, 'reporting_lag_days': REPORTING_LAG_DAYS,
                    'implementation_sha256': digest(Path(__file__).read_bytes()),
                    'trade_plan_sha256': plan_sha, 'chokepoints': {k: list(v) for k, v in CHOKEPOINTS.items()},
                    'snapshot_id': snapshot_id, 'source': source, 'inputs': inputs, 'outputs': outputs,
                    'previous_snapshot_id': (previous_manifest.get('previous_snapshot_id') if previous_manifest and previous_manifest['snapshot_id'] == snapshot_id
                                             else previous_manifest['snapshot_id'] if previous_manifest else None),
                    'documentation': ['https://portwatch.imf.org/pages/data-and-methodology', ITEM_URL+'?f=json',
                                      'https://www.imf.org/-/media/files/publications/wp/2025/english/wpiea2025093-print-pdf.pdf'],
                    'citation': 'Sources: UN Global Platform; IMF PortWatch (portwatch.imf.org).',
                    'limitations': LIMITATIONS}
        saved = root/f'snapshots/{snapshot_id}/manifest.json'
        _immutable(saved, _json_bytes(manifest))
        load_snapshot(root, manifest_path=saved, replay=True)
        write_json_if_changed(root/'manifest.json', manifest)  # One atomic pointer activates both tables.
        return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--offline', action='store_true', help='Verify and replay the active archived snapshot; no network or new dates')
    parser.add_argument('--as-of', help='UTC date (whole day) or exact timestamp; historical exports require a separate root')
    args = parser.parse_args()
    manifest = refresh(args.root, offline=args.offline, as_of=args.as_of)
    print(json.dumps({'snapshot_id': manifest['snapshot_id'], 'as_of_utc': manifest['as_of_utc'],
                      'fetched_at': manifest['fetched_at'], 'source_rows': manifest['source']['record_count']}, indent=2))


if __name__ == '__main__':
    main()
