"""Deterministic change evidence, not an anomaly detector or notification client."""
from __future__ import annotations
import csv
import datetime as dt
import decimal
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sqlite3

VERSION = 1
RECEIPT_FIELDS = {'fetched_at', 'generated_at', 'retrieved_at', 'accessed_at',
                  'snapshot_id', 'source_snapshot_id', 'manifest_sha256'}
ARCHIVES = {'raw', 'snapshots', 'prior_snapshots', 'source_recovery', 'sources', 'vendor', 'tests'}
LAKE_POLICY = {'lower_red_reference_m': -213.0, 'absolute_daily_change_review_m': 0.25,
               'interpretation': 'Reference crossing or operational review threshold, not a statistical anomaly or prophetic claim',
               'reference_source': 'https://hadshon.education.gov.il/articles/kineret/'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def canonical(value, field=''):
    if field == 'dimensions':
        parsed = json.loads(value or '{}')
        # Provider quote enumeration is not price-series identity. Quote dates remain.
        parsed.pop('source_quote_ordinal', None)
        return json.dumps(parsed, sort_keys=True, separators=(',', ':'))
    if re.fullmatch(r'-?(?:0|[1-9]\d*)\.\d+(?:[eE][+-]?\d+)?|-?(?:0|[1-9]\d*)[eE][+-]?\d+', str(value)):
        with decimal.localcontext() as context:
            context.prec = 12  # Suppress insignificant CSV float rendering changes.
            return str((+decimal.Decimal(value)).normalize())
    return value


def csv_summary(path, logical_name):
    payload = Path(path).read_bytes()
    if str(path).endswith('.gz'):
        payload = gzip.decompress(payload)
    try:
        text = payload.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = payload.decode('cp1252')
    reader = csv.DictReader(io.StringIO(text, newline=''))
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError(f'Invalid CSV header: {logical_name}')
    ignored = set(RECEIPT_FIELDS)
    lake = logical_name.endswith('/kinneret_levels.csv')
    if lake:
        ignored.add('source_record_id')  # CKAN renumbers all rows after an insertion.
    flu = logical_name.endswith('seasonal_flu_weekly.csv')
    if flu:
        ignored.add('latest_expected_week')
    if logical_name.endswith('affordability_latest_series.csv'):
        ignored.add('age_months')
    if '/trade_shipping/active/' in logical_name:
        ignored.add('ObjectId')  # PortWatch's storage ID is not route/date identity.
    if logical_name.endswith('seasonal_flu_row_quality.csv'):
        ignored.add('source_row')
    if '/eclipses/' in logical_name:
        ignored.update({'prediction_status', 'status'})  # Calendar labels, not new geometry.
    fields = sorted(set(reader.fieldnames) - ignored)
    rows, lake_records, lake_values = [], {}, {}
    for row in reader:
        # Active-source calendar padding and reporting-lag rows are not usable observations.
        if 'usable' in row and row['usable'].lower() != 'true':
            continue
        if logical_name.endswith('flares_swpc.csv') and not re.match(r'^[MX]', row.get('class', '')):
            continue
        # A newly expected but unobserved week/month is not a new measurement.
        if row.get('status') in {'unobserved_week', 'reporting lag'}:
            continue
        normalized = [canonical(row.get(key, ''), key) for key in fields]
        rows.append(normalized)
        if lake:
            key = row['observation_date']
            if key in lake_records:
                raise ValueError('Duplicate Kinneret measurement date')
            lake_records[key] = digest(normalized)
            lake_values[key] = float(row['level_m'])
            if not math.isfinite(lake_values[key]):
                raise ValueError('Nonfinite Kinneret measurement')
    result = {'fields': fields, 'rows': len(rows), 'sha256': digest(sorted(rows))}
    if lake:
        result.update(kind='lake', records=lake_records, measurements=lake_values)
    return result


def snapshot(workspace, repos, git):
    workspace = Path(workspace)
    out = {'schema_version': VERSION, 'tables': {}}
    for repo in repos:
        for name in git(repo, 'ls-files', '-z').split('\0'):
            path = Path(name)
            if not name.endswith(('.csv', '.csv.gz')) or set(path.parts) & ARCHIVES:
                continue
            if path.name in {'seasonal_flu_weekly.csv', 'seasonal_flu_baseline_windows.csv', 'seasonal_flu_row_quality.csv'}:
                continue  # Clock-only rolling views age out unchanged history. WHO observations remain compared.
            # Copied Israel/eclipses tables already have one authoritative feeder representation.
            if repo == 'correlations' and name.startswith(('data/israel_monitoring/', 'data/celestial_monitoring/')):
                continue
            out['tables'][repo+'/'+name] = csv_summary(workspace/repo/name, repo+'/'+name)
    base = workspace/'correlations/data'
    for source in ['climate_indices', 'economic_sources', 'trade_shipping']:
        manifest = json.loads((base/source/'manifest.json').read_text())
        for name, record in manifest['outputs'].items():
            # Coverage receipts/expected calendars advance daily; eligible tables carry new usable periods.
            if 'coverage' in name:
                continue
            logical = f'correlations/data/{source}/active/{name}'
            out['tables'][logical] = csv_summary(base/source/record['path'], logical)
    for file, start in [('quakes.sqlite', '1965-01-01'), ('quakes_1900.sqlite', '1900-01-01')]:
        path = workspace/'earthquakes'/file
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True) as db:
            lower = int(dt.datetime.fromisoformat(start).replace(tzinfo=dt.timezone.utc).timestamp()*1000)
            rows = db.execute('SELECT * FROM quakes WHERE mag>=6.5 AND time_ms>=? ORDER BY id', (lower,)).fetchall()
            out['tables']['earthquakes/'+file+'/major_quakes'] = {'rows': len(rows), 'sha256': digest(rows)}
            if file == 'quakes.sqlite':
                rows = db.execute('SELECT * FROM significant_quakes ORDER BY id').fetchall()
                out['tables']['earthquakes/'+file+'/significant_quakes'] = {'rows': len(rows), 'sha256': digest(rows)}
    intervals = json.loads((base/'swpc_observation_intervals.json').read_text())['intervals']
    gaps = [[left['end'], right['start']] for left, right in zip(intervals, intervals[1:])]
    out['tables']['correlations/swpc_observation_gaps'] = {'rows': len(gaps), 'sha256': digest(gaps)}
    climate = json.loads((workspace/'israel-rain-agriculture/results/climate_monitor.json').read_text())
    payload = {key: climate[key] for key in ['product', 'latest_month', 'holdout', 'coverage', 'latest_complete_rain_year']}
    out['tables']['israel-rain-agriculture/climate_eligibility'] = {'sha256': digest(payload)}
    return out


def compare(before, after, policy=None):
    policy = dict(LAKE_POLICY if policy is None else policy)
    if not math.isfinite(policy['lower_red_reference_m']) or not math.isfinite(policy['absolute_daily_change_review_m']) or policy['absolute_daily_change_review_m'] <= 0:
        raise ValueError('Invalid approved operational lake review policy')
    if before is None:
        return {'notification_needed': False, 'reasons': [], 'routine_changes': [], 'baseline_initialized': True}
    if before.get('schema_version') != VERSION or after.get('schema_version') != VERSION:
        raise ValueError('Semantic baseline version changed; explicit review required')
    reasons, routine = [], []
    for name in sorted(set(before['tables']) | set(after['tables'])):
        old, new = before['tables'].get(name), after['tables'].get(name)
        if old == new:
            continue
        change = {'table': name, 'before_rows': old.get('rows') if old else None,
                  'after_rows': new.get('rows') if new else None}
        if old and new and old.get('kind') == new.get('kind') == 'lake':
            removed = sorted(set(old['records'])-set(new['records']))
            revised = sorted(k for k in set(old['records']) & set(new['records']) if old['records'][k] != new['records'][k])
            change.update(removed_dates=removed, revised_dates=revised,
                          added_dates=sorted(set(new['records'])-set(old['records'])))
            review = []
            dates = sorted(new['measurements'])
            for date in change['added_dates']:
                index = dates.index(date)
                if index == 0:
                    continue
                prior = dates[index-1]
                previous, current = new['measurements'][prior], new['measurements'][date]
                elapsed = (dt.date.fromisoformat(date)-dt.date.fromisoformat(prior)).days
                rate = (current-previous)/elapsed
                reference = policy['lower_red_reference_m']
                crossing = previous >= reference > current or previous <= reference < current
                if crossing or abs(rate) > policy['absolute_daily_change_review_m']:
                    review.append({'previous_date':prior, 'date':date, 'elapsed_days':elapsed,
                        'previous_level_m':previous, 'level_m':current, 'change_per_elapsed_day_m':rate,
                        'crossed_lower_red_reference':crossing, 'operational_review_threshold_exceeded':abs(rate)>policy['absolute_daily_change_review_m']})
            change.update(physical_review=review, policy=policy)
            (reasons if removed or revised or review or old['fields'] != new['fields'] else routine).append(change)
        else:
            change['reason'] = 'changed observations, usable periods, coverage, or analytical results; descriptive review required'
            reasons.append(change)
    return {'notification_needed': bool(reasons), 'reasons': reasons, 'routine_changes': routine, 'baseline_initialized': False}
