"""Versioned NOAA climate indices, with complete-year controls and atomic activation."""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import html
import io
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

from monitoring.feeds import BASE, Client
from source_tracking import write_json_if_changed

ROOT = BASE / 'data/climate_indices'
URLS = {
    'cpc_definition': 'https://www.cpc.ncep.noaa.gov/data/indices/',
    'dmi_definition': 'https://psl.noaa.gov/data/timeseries/month/DMI/',
    'rni': 'https://www.cpc.ncep.noaa.gov/data/indices/Rnino34.ascii.txt',
    'roni': 'https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt',
    'dmi': 'https://psl.noaa.gov/data/timeseries/month/data/dmi.had.long.data',
}
VERSIONS = {'rni': 'Relative ERSSTv6; 1991-2020 baseline',
            'roni': 'Relative ERSSTv6; 1991-2020 baseline; three-month running mean',
            'dmi': 'HadISST1.1; NOAA PSL Dipole Mode Index'}
SEASONS = 'DJF JFM FMA MAM AMJ MJJ JJA JAS ASO SON OND NDJ'.split()


def digest(content):
    return hashlib.sha256(content).hexdigest()


def cutoff(as_of=None):
    value = as_of if as_of is not None else dt.datetime.now(dt.timezone.utc)
    stamp = pd.Timestamp(value)
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime) or isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        stamp += pd.Timedelta(days=1)  # A date-only argument means through that full date.
    return stamp.tz_convert('UTC').tz_localize(None) if stamp.tzinfo else stamp


def validate_definitions(payloads):
    cpc = html.unescape(re.sub(r'<[^>]+>', ' ', payloads['cpc_definition'].decode()))
    cpc = ' '.join(cpc.split()).replace('–', '-').replace('—', '-')
    for label in ['Monthly Relative ERSSTv6', 'Seasonal Relative ERSSTv6']:
        if not re.search(re.escape(label)+r'\s*\(1991\s*-\s*2020 base period\)', cpc):
            raise ValueError('NOAA CPC climate product version or baseline changed; review before splicing history')
    if 'HadISST1.1' not in payloads['dmi_definition'].decode():
        raise ValueError('NOAA PSL DMI source product changed; review required')


def _number(text, missing=()):
    value = float(text)
    if value in missing:
        return np.nan
    if not np.isfinite(value) or abs(value) > 20:
        raise ValueError('Invalid climate anomaly or unrecognized missing-value code')
    return value


def parse_cpc(payload, *, seasonal=False):
    lines = payload.decode().strip().splitlines()
    expected = ['SEAS', 'YR', 'ANOM'] if seasonal else ['YR', 'MTH', 'ANOM']
    if not lines or lines[0].split() != expected:
        raise ValueError('NOAA CPC index schema changed')
    rows = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) != 3:
            raise ValueError('Malformed NOAA CPC index record')
        if seasonal:
            season, year = fields[:2]
            if season not in SEASONS:
                raise ValueError('Unknown RONI season')
            center = pd.Timestamp(year=int(year), month=SEASONS.index(season)+1, day=1)
            start = center-pd.DateOffset(months=1)
            end = center+pd.DateOffset(months=2)-pd.Timedelta(days=1)
            row = {'year': int(year), 'season': season}
        else:
            year, month = map(int, fields[:2])
            start = pd.Timestamp(year=year, month=month, day=1)
            end = start+pd.offsets.MonthEnd(0)
            row = {'year': year, 'month': month}
        rows.append({**row, 'period_start': start.date().isoformat(), 'period_end': end.date().isoformat(),
                     'value': _number(fields[2], (-99.9, -99.99, -999, -999.9))})
    result = pd.DataFrame(rows)
    if result.empty or result.duplicated(['year', 'season' if seasonal else 'month']).any():
        raise ValueError('Empty or duplicate NOAA CPC index periods')
    return result.sort_values('period_start').reset_index(drop=True)


def parse_dmi(payload):
    lines = [line.strip() for line in payload.decode().splitlines() if line.strip()]
    bounds = lines[0].split() if lines else []
    if len(bounds) != 2 or not all(re.fullmatch(r'\d{4}', v) for v in bounds):
        raise ValueError('Invalid NOAA PSL year bounds')
    first, last = map(int, bounds)
    if last < first or last-first > 300:
        raise ValueError('Invalid NOAA PSL year range')
    count = last-first+1
    if len(lines) < count+2:
        raise ValueError('Truncated NOAA PSL data')
    missing = float(lines[count+1])  # PSL standard format declares its sentinel after year rows.
    if not np.isfinite(missing) or abs(missing) <= 20:
        raise ValueError('Missing NOAA PSL sentinel declaration')
    rows = []
    for year, line in zip(range(first, last+1), lines[1:count+1]):
        fields = line.split()
        if len(fields) != 13 or int(fields[0]) != year:
            raise ValueError('Missing, reordered or malformed NOAA PSL year')
        for month, text in enumerate(fields[1:], 1):
            start = pd.Timestamp(year=year, month=month, day=1)
            rows.append({'year': year, 'month': month, 'period_start': start.date().isoformat(),
                         'period_end': (start+pd.offsets.MonthEnd(0)).date().isoformat(),
                         'value': _number(text, (missing,))})
    return pd.DataFrame(rows)


def build_tables(payloads, as_of=None):
    validate_definitions(payloads)
    bound = cutoff(as_of)
    monthly_parts = []
    for name, data in [('rni', parse_cpc(payloads['rni'])), ('dmi', parse_dmi(payloads['dmi']))]:
        data['index'] = name
        data['source_url'] = URLS[name]
        data['source_version'] = VERSIONS[name]
        data['unit'] = 'degrees_C_anomaly'
        data['period_complete'] = pd.to_datetime(data.period_end)+pd.Timedelta(days=1) <= bound
        data['usable'] = data.value.notna() & data.period_complete
        monthly_parts.append(data)
    monthly = pd.concat(monthly_parts, ignore_index=True).sort_values(['index', 'period_start'])
    seasonal = parse_cpc(payloads['roni'], seasonal=True)
    seasonal['source_url'] = URLS['roni']
    seasonal['source_version'] = VERSIONS['roni']
    seasonal['unit'] = 'degrees_C_anomaly'
    seasonal['period_complete'] = pd.to_datetime(seasonal.period_end)+pd.Timedelta(days=1) <= bound
    seasonal['usable'] = seasonal.value.notna() & seasonal.period_complete
    # The two CPC products must belong to a consistent source vintage.
    rni = monthly[monthly['index'].eq('rni')].set_index('period_start').value
    for row in seasonal[seasonal.value.notna()].itertuples():
        months = pd.date_range(row.period_start, row.period_end, freq='MS').strftime('%Y-%m-%d')
        values = rni.reindex(months)
        if len(values) != 3 or values.isna().any() or abs(values.mean()-row.value) > .015:
            raise ValueError('RNI/RONI vintage or three-month alignment mismatch')
    annual_rows, coverage = [], []
    for year in range(1950, bound.year+1):
        record = {'year': year}
        for name in ['rni', 'dmi']:
            g = monthly[monthly['index'].eq(name) & monthly.year.eq(year) & monthly.usable]
            record[name] = float(g.value.mean()) if len(g) == 12 and g.month.nunique() == 12 else np.nan
            coverage.append({'year': year, 'index': name, 'observed_months': len(g),
                             'required_months': 12, 'year_complete': pd.Timestamp(year=year+1, month=1, day=1) <= bound})
        if pd.Timestamp(year=year+1, month=1, day=1) <= bound and all(np.isfinite(record[x]) for x in ['rni', 'dmi']):
            annual_rows.append(record)
    annual = pd.DataFrame(annual_rows, columns=['year', 'rni', 'dmi'])
    if annual.empty:
        raise ValueError('No complete paired annual climate controls')
    return {'monthly.csv': monthly.reset_index(drop=True), 'roni_seasonal.csv': seasonal,
            'annual.csv': annual, 'annual_coverage.csv': pd.DataFrame(coverage)}


def load_snapshot(root=ROOT):
    root = Path(root)
    manifest = json.loads((root/'manifest.json').read_text())
    if manifest.get('schema_version') != 1 or manifest.get('versions') != VERSIONS:
        raise ValueError('Climate source contract changed')
    if set(manifest.get('inputs', {})) != set(URLS):
        raise ValueError('Incomplete climate source archive')
    for name, record in manifest['inputs'].items():
        path = root/record['path']
        if (not path.resolve().is_relative_to(root.resolve()) or record['source_url'] != URLS[name]
                or digest(gzip.decompress(path.read_bytes())) != record['sha256']):
            raise ValueError('Climate source archive missing or hash mismatch')
    tables = {}
    for name, record in manifest['outputs'].items():
        path = root/record['path']
        if not path.resolve().is_relative_to(root.resolve()) or digest(path.read_bytes()) != record['sha256']:
            raise ValueError('Climate output missing or hash mismatch')
        tables[name] = pd.read_csv(path)
        if len(tables[name]) != record['rows']:
            raise ValueError('Climate output row-count mismatch')
    if set(tables) != {'monthly.csv', 'roni_seasonal.csv', 'annual.csv', 'annual_coverage.csv'}:
        raise ValueError('Incomplete climate snapshot')
    return tables, manifest


def _observed_keys(table, seasonal=False):
    keys = ['year', 'season'] if seasonal else ['index', 'year', 'month']
    return set(map(tuple, table.loc[table.value.notna(), keys].to_numpy()))


def refresh(root=ROOT, *, offline=False, client=None, as_of=None):
    root = Path(root)
    bound = cutoff(as_of)
    client = client or Client(cache=BASE/'.cache/climate_indices', offline=offline)
    payloads = {name: client.get(url) for name, url in URLS.items()}
    tables = build_tables(payloads, bound)
    if (root/'manifest.json').exists():
        previous, previous_manifest = load_snapshot(root)
        if bound < cutoff(previous_manifest['as_of_utc']):
            raise ValueError('Climate activation cutoff regressed; historical exports require a separate output root')
        for name, seasonal in [('monthly.csv', False), ('roni_seasonal.csv', True)]:
            if not _observed_keys(previous[name], seasonal) <= _observed_keys(tables[name], seasonal):
                raise ValueError('Climate history lost previously observed periods; review before activation')
        if not set(previous['annual.csv'].year) <= set(tables['annual.csv'].year):
            raise ValueError('Climate annual coverage regressed; historical exports require a separate output root')
    contents = {name: table.to_csv(index=False).encode() for name, table in tables.items()}
    snapshot_id = digest(b''.join(name.encode()+contents[name] for name in sorted(contents)))
    outputs = {}
    for name, content in contents.items():
        relative = f'snapshots/{snapshot_id}/{name}'
        path = root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content)
        elif path.read_bytes() != content:
            raise ValueError('Immutable climate snapshot conflict')
        outputs[name] = {'path': relative, 'sha256': digest(content), 'rows': len(tables[name])}
    raw = {}
    for name, content in payloads.items():
        relative = f'raw/{name}/{digest(content)}.gz'
        path = root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        archived = gzip.compress(content, mtime=0)
        if not path.exists():
            path.write_bytes(archived)
        elif path.read_bytes() != archived:
            raise ValueError('Immutable climate input conflict')
        raw[name] = {'path': relative, 'sha256': digest(content), 'source_url': URLS[name]}
    monthly, seasonal, annual = tables['monthly.csv'], tables['roni_seasonal.csv'], tables['annual.csv']
    latest = {name: monthly.loc[monthly['index'].eq(name) & monthly.usable, 'period_end'].max() for name in ['rni', 'dmi']}
    latest['roni'] = seasonal.loc[seasonal.usable, 'period_end'].max()
    manifest = {'schema_version': 1, 'versions': VERSIONS, 'as_of_utc': bound.isoformat(),
                'fetched_at': max(r['fetched_at'] for r in client.requests), 'requests': client.requests,
                'snapshot_id': snapshot_id, 'inputs': raw, 'outputs': outputs,
                'observed_through': latest, 'paired_annual_years': [int(annual.year.min()), int(annual.year.max())],
                'definitions': {'rni': 'Monthly relative Nino3.4 anomaly; annual means require12 Jan-Dec months.',
                                'roni': 'Three-month running mean displayed by full observation window; not used as a calendar-year control.',
                                'dmi': 'Monthly Indian Ocean west-minus-east SST anomaly gradient.'},
                'limitations': ['Current revised source vintages, not real-time historical predictors.',
                                'Recent CPC estimates may change; NOAA PSL describes DMI as preliminary.',
                                'Global ocean indices do not measure local rainfall or prove a causal climate pathway.',
                                'Missing months and incomplete years are never filled. Product changes require review.']}
    # Only this atomic pointer activates all four already-validated outputs together.
    write_json_if_changed(root/'manifest.json', manifest)
    return manifest


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args(argv)
    result = refresh(args.output, offline=args.offline)
    print(json.dumps({key: result[key] for key in ['observed_through', 'paired_annual_years', 'snapshot_id']}, indent=2))


if __name__ == '__main__':
    main()
