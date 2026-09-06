"""Reproducible, read-only investigation of missing WFP/IPC source coverage.

Downloads are evidence only. Nothing here writes active monitoring observations,
changes an eligibility rule, or treats a failed request as absent data.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import gzip
import hashlib
import io
import json
import re
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

import numpy as np
import pandas as pd
import requests

from monitoring.feeds import normalize_wfp

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / 'data/source_recovery'
HDX = 'https://data.humdata.org/api/3/action/'
PACKAGES = {
    'wfp_yem': 'wfp-food-prices-for-yemen',
    'wfp_eth': 'wfp-food-prices-for-ethiopia',
    'wfp_legacy': 'wfp-food-prices',
    'wfp_global_current': 'global-wfp-food-prices',
    'ipc': 'global-acute-food-insecurity-country-data',
}
PAGES = {
    'hdx_wfp_migration': 'https://centre.humdata.org/getting-up-to-speed-wfp-food-data-on-hdx/',
    'ipc_api': 'https://www.ipcinfo.org/ipc-country-analysis/api/',
    'ipc_docs': 'https://docs.api.ipcinfo.org/',
    'ipc_api_schema': 'https://docs.api.ipcinfo.org/api/public/openapi.json',
    'worldbank_yemen_estimates': 'https://microdata.worldbank.org/index.php/catalog/4508/study-description',
    'fews_yemen_2015_terms_of_trade': 'https://fews.net/sites/default/files/documents/reports/Yemen_2015_03_PB.pdf',
}
SEARCHES = {
    'search_wfp_yemen': 'Yemen food prices wages',
    'search_wfp_ethiopia': 'Ethiopia food prices wages',
    'search_ipc_geography': 'IPC shapefile',
}


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def write_json(path, value):
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_bytes() != payload:
        temp = path.with_suffix(path.suffix + '.tmp')
        temp.write_bytes(payload)
        temp.replace(path)


class Evidence:
    """Content-addressed public responses with explicit HTTP/transport failures."""

    def __init__(self, output=DEFAULT_OUTPUT, offline=False, session=None):
        self.output = Path(output)
        self.offline = offline
        self.session = session or requests.Session()
        self.session.headers['User-Agent'] = 'Biblejustin-correlations-source-recovery/1.0'
        self.manifest_path = self.output / 'requests.json'
        self.records = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {}

    def read(self, name):
        record = self.records[name]
        if 'path' not in record:
            return None
        path = (self.output / record['path']).resolve()
        if not path.is_relative_to(self.output.resolve()):
            raise ValueError('Evidence path escapes output directory')
        payload = gzip.decompress(path.read_bytes())
        if sha(payload) != record['sha256']:
            raise ValueError('Damaged source-recovery archive')
        return payload if record['status'] == 'available' else None

    def fetch(self, name, url, max_bytes=150_000_000):
        if self.offline:
            if name not in self.records or self.records[name]['url'] != url:
                raise ValueError(f'No matching archived recovery request: {name}')
            return self.read(name)
        record = {'url': url, 'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat()}
        began = time.monotonic()
        try:
            with self.session.get(url, timeout=(15, 45), stream=True) as response:
                final = urlsplit(response.url)
                # Publisher downloads may redirect to temporary signed storage
                # URLs. Preserve the canonical request and destination path only.
                if final.hostname and final.hostname.endswith('amazonaws.com'):
                    final = final._replace(query='', fragment='')
                record.update(http_status=response.status_code, final_url=urlunsplit(final),
                              last_modified=response.headers.get('Last-Modified'))
                pieces, size = [], 0
                for part in response.iter_content(64 * 1024):
                    if time.monotonic() - began > 180:
                        raise ValueError('Request exceeds declared 180-second audit duration')
                    size += len(part)
                    if size > max_bytes:
                        raise ValueError(f'Response exceeds declared {max_bytes}-byte audit bound')
                    pieces.append(part)
                payload = b''.join(pieces)
                if not payload:
                    raise ValueError('Empty response')
                path = Path('raw') / (sha(payload) + '.gz')
                target = self.output / path
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if gzip.decompress(target.read_bytes()) != payload:
                        raise ValueError('Existing archive differs from content hash')
                else:
                    target.write_bytes(gzip.compress(payload, mtime=0))
                record.update(path=str(path), sha256=sha(payload), bytes=len(payload),
                              status='available' if response.ok else 'http_error')
                self.records[name] = record
                write_json(self.manifest_path, self.records)
                return payload if response.ok else None
        except (requests.RequestException, ValueError) as exc:
            record.update(status='request_failed', error=f'{type(exc).__name__}: {exc}')
            self.records[name] = record
            write_json(self.manifest_path, self.records)
            return None


def csv(payload):
    d = pd.read_csv(io.BytesIO(payload), dtype=str, low_memory=False)
    if len(d) and str(d.iloc[0, 0]).startswith('#'):
        d = d.iloc[1:].copy()
    return d


def recover_legacy_ranges(output=DEFAULT_OUTPUT, chunk_bytes=16_000_000):
    """Resume a complete public archive via verified, version-consistent ranges.

    Partial chunks never become a data source. Every byte must be covered once,
    with identical strong ETag/Last-Modified and explicit HTTP Content-Range.
    """
    evidence = Evidence(output, offline=True)
    metadata = json.loads(evidence.read('wfp_legacy_metadata'))['result']
    resources = metadata['resources']
    if len(resources) != 1:
        raise ValueError('Ambiguous legacy archive')
    url, total = resources[0]['url'], int(resources[0]['size'])
    ranges = [(start, min(start + chunk_bytes, total) - 1) for start in range(0, total, chunk_bytes)]
    receipt_path = Path(output) / 'legacy_range_receipts.json'
    receipts = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}

    def download(bounds):
        start, end = bounds; key = f'{start}-{end}'
        if key in receipts:
            receipt = receipts[key]
            payload = gzip.decompress((Path(output) / receipt['path']).read_bytes())
            if receipt['source_url'] != url or receipt['total_bytes'] != total or len(payload) != end-start+1 or sha(payload) != receipt['sha256']:
                raise ValueError('Damaged or incompatible resumed range')
            return key, receipt
        began = time.monotonic()
        with requests.get(url, headers={'Range': f'bytes={start}-{end}',
                'User-Agent': 'Biblejustin-correlations-source-recovery/1.0'},
                timeout=(15, 45), stream=True) as response:
            expected = f'bytes {start}-{end}/{total}'
            if response.status_code != 206 or response.headers.get('Content-Range') != expected:
                raise ValueError(f'Legacy range {key} returned no exact partial-content contract')
            etag = response.headers.get('ETag', '')
            modified = response.headers.get('Last-Modified', '')
            if not re.fullmatch(r'"[^"]+"', etag) or not modified:
                raise ValueError('Legacy ranges require a strong version marker and modification date')
            parts, size = [], 0
            for part in response.iter_content(64*1024):
                if time.monotonic()-began > 180:
                    raise ValueError('Legacy range exceeded 180-second bound')
                size += len(part)
                if size > end-start+1:
                    raise ValueError('Legacy range overflow')
                parts.append(part)
            payload = b''.join(parts)
            if len(payload) != end-start+1:
                raise ValueError('Incomplete legacy range')
        relative = Path('ranges') / f'{start}-{end}-{sha(payload)}.gz'
        target = Path(output) / relative; target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and gzip.decompress(target.read_bytes()) != payload:
            raise ValueError('Immutable range conflict')
        if not target.exists():
            target.write_bytes(gzip.compress(payload, mtime=0))
        return key, {'source_url': url, 'start': start, 'end': end, 'total_bytes': total,
                     'http_status': 206, 'content_range': expected, 'etag': etag,
                     'last_modified': modified, 'sha256': sha(payload), 'path': str(relative),
                     'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat()}

    failures = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(download, bounds): bounds for bounds in ranges}
        for future in as_completed(futures):
            try:
                key, receipt = future.result(); receipts[key] = receipt
                write_json(receipt_path, receipts)
                print(f'Verified archive range {key}', flush=True)
            except (requests.RequestException, ValueError, OSError) as exc:
                failures.append({'range': list(futures[future]), 'error': f'{type(exc).__name__}: {exc}'})
    if failures:
        write_json(Path(output) / 'legacy_range_failures.json', failures)
        raise ValueError(f'{len(failures)} legacy ranges unavailable; verified chunks retained for resume')
    selected = [receipts[f'{a}-{b}'] for a,b in ranges]
    if len({(x['etag'], x['last_modified']) for x in selected}) != 1:
        raise ValueError('Legacy archive changed between ranges; no combined snapshot activated')
    payload = b''.join(gzip.decompress((Path(output) / x['path']).read_bytes()) for x in selected)
    if len(payload) != total:
        raise ValueError('Combined legacy archive byte count mismatch')
    relative = Path('raw') / (sha(payload) + '.gz'); target = Path(output) / relative
    if target.exists() and gzip.decompress(target.read_bytes()) != payload:
        raise ValueError('Immutable legacy archive conflict')
    if not target.exists():
        target.write_bytes(gzip.compress(payload, mtime=0))
    prior = evidence.records.get('wfp_legacy_prices')
    if prior and prior.get('status') == 'available' and prior.get('sha256') == sha(payload):
        return prior
    evidence.records['wfp_legacy_prices'] = {
        'url': url, 'status': 'available', 'path': str(relative), 'sha256': sha(payload),
        'bytes': total, 'retrieval_method': 'complete non-overlapping HTTP ranges; common strong ETag',
        'range_receipts': receipt_path.name, 'etag': selected[0]['etag'],
        'last_modified': selected[0]['last_modified'],
        'fetched_at': max(x['fetched_at'] for x in selected), 'prior_attempts': [prior] if prior else []}
    write_json(evidence.manifest_path, evidence.records)
    return evidence.records['wfp_legacy_prices']


def wage_coverage(d, country, label):
    """Source labels stay separate: casual, qualified, aggregate != frozen wage."""
    required = {'commodity', 'commodity_id', 'unit', 'priceflag', 'date', 'market_id', 'price'}
    if not required <= set(d):
        raise ValueError('WFP audit schema changed')
    d = d.copy()
    d['date'] = pd.to_datetime(d.date, errors='raise')
    d['price'] = pd.to_numeric(d.price, errors='coerce')
    d = d[d.commodity.str.contains('wage', case=False, na=False) & d.price.gt(0) & np.isfinite(d.price)]
    rows = []
    for identity, group in d.groupby(['commodity_id', 'commodity', 'unit', 'priceflag'], dropna=False, sort=True):
        row = dict(zip(['commodity_id', 'commodity', 'unit', 'priceflag'], identity))
        row.update(source=label, country=country, observations=len(group), markets=group.market_id.nunique(),
                   first=str(group.date.min().date()), last=str(group.date.max().date()))
        for year in range(2015, 2020):
            row[f'months_{year}'] = group[group.date.dt.year.eq(year)].date.dt.to_period('M').nunique()
        rows.append(row)
    return rows


def pair_coverage(d, country, label, url):
    normalized = normalize_wfp(d, country, url)
    ratios = normalized[normalized.metric.eq('staple_kg_per_daily_wage')].copy()
    rows = []
    if ratios.empty:
        return rows
    # Stable full dimensions exclude only quote-lineage counters; no source names
    # or units are rewritten to splice the legacy export into current series.
    for dimensions, group in ratios.groupby('dimensions', sort=True):
        dims = json.loads(dimensions)
        for key in ['food_quote_count', 'wage_quote_count', 'wage_original_units', 'pairing_rule']:
            dims.pop(key, None)
        group = group.copy()
        group['audit_identity'] = json.dumps(dims, sort_keys=True)
        rows.append(group)
    combined = pd.concat(rows, ignore_index=True)
    result = []
    for identity, group in combined.groupby('audit_identity', sort=True):
        periods = pd.to_datetime(group.period_start).dt.to_period('M')
        counts = {str(year): int(periods[periods.dt.year.eq(year)].nunique()) for year in range(2015, 2020)}
        result.append({'country': country, 'source': label, 'identity': identity, 'source_url': url,
                       'first': str(periods.min()), 'last': str(periods.max()),
                       'baseline_months': sum(counts.values()), 'baseline_year_counts': json.dumps(counts, sort_keys=True),
                       'baseline_coverage_eligible': sum(counts.values()) >= 36 and min(counts.values()) >= 6})
    return result


def ipc_schema(d, resource):
    columns = list(d)
    identifiers = [x for x in columns if re.search(r'(^|[_ ])(id|code|pcode)([_ ]|$)', x, re.I)]
    geometry = [x for x in columns if re.search(r'geometry|geojson|wkt|polygon', x, re.I)]
    pilot_bounds = {}
    if {'Country', 'From'} <= set(d):
        pilot = d[d.Country.isin(['ISR', 'PSE', 'LBN', 'UKR', 'SDN', 'ETH', 'SOM', 'YEM'])]
        for country, group in pilot.groupby('Country', sort=True):
            dates = pd.to_datetime(group.From, errors='raise')
            pilot_bounds[country] = {'first_period_start': str(dates.min().date()),
                                     'last_period_start_including_projections': str(dates.max().date())}
    return {'resource': resource, 'rows': len(d), 'columns': columns,
            'candidate_identifier_columns': identifiers, 'candidate_geometry_columns': geometry,
            'country_labels': sorted(d.Country.dropna().unique()) if 'Country' in d else [],
            'pilot_period_start_bounds': pilot_bounds,
            'identity_or_geography_certified': False,
            'note': 'Schema candidates alone cannot certify stable publisher identity, footprint, or non-overlap.'}


def legacy_extract(payload):
    """Count full CSV while retaining only target countries in working memory."""
    total, selected, columns = 0, [], []
    for frame in pd.read_csv(io.BytesIO(payload), dtype=str, chunksize=100_000):
        columns = list(frame)
        if not {'adm0_name', 'cm_id', 'cm_name', 'um_name', 'mp_year', 'mp_month'} <= set(columns):
            raise ValueError('Legacy WFP audit schema changed')
        if len(frame) and str(frame.iloc[0, 0]).startswith('#'):
            frame = frame.iloc[1:].copy()
        total += len(frame)
        selected.append(frame[frame.adm0_name.isin(['Yemen', 'Ethiopia'])])
    if not total:
        raise ValueError('Empty legacy WFP archive')
    return total, columns, pd.concat(selected, ignore_index=True)


def run(output=DEFAULT_OUTPUT, offline=False):
    evidence = Evidence(output, offline)
    packages, inventory, outcomes = {}, [], {}
    for name, package in PACKAGES.items():
        payload = evidence.fetch(name + '_metadata', HDX + 'package_show?' + urlencode({'id': package}))
        if payload is None:
            continue
        result = json.loads(payload)
        if not result.get('success'):
            outcomes[name] = {'status': 'api_error', 'error': result.get('error')}
            continue
        packages[name] = result['result']
        for resource in result['result'].get('resources', []):
            inventory.append({'package': package, **{k: resource.get(k) for k in
                ['id', 'name', 'url', 'format', 'size', 'last_modified', 'created']}})
    for name, query in SEARCHES.items():
        payload = evidence.fetch(name, HDX + 'package_search?' + urlencode({'q': query, 'rows': 100}))
        if payload:
            data = json.loads(payload)
            outcomes[name] = ({'status': 'available', 'query': query, 'count': data['result']['count'],
                               'returned': [{'name': x['name'], 'title': x['title']} for x in data['result']['results']],
                               'complete': data['result']['count'] <= 100}
                              if data.get('success') else {'status': 'api_error', 'error': data.get('error')})
    for name, url in PAGES.items():
        evidence.fetch(name, url)
    evidence.fetch('wfp_legacy_datastore', HDX + 'datastore_search?' + urlencode({
        'resource_id': '12d7c8e3-eff9-4db0-93b7-726825c4fe9a',
        'filters': json.dumps({'adm0_name': ['Yemen', 'Ethiopia']}), 'limit': 1}))
    for name in ['wfp_yem', 'wfp_eth']:
        if name in packages:
            evidence.fetch(name + '_activity', HDX + 'package_activity_list?' +
                           urlencode({'id': packages[name]['id'], 'limit': 100}))
    wages, pairs, schemas, current = [], [], [], {}
    for key, country in [('wfp_yem', 'YEM'), ('wfp_eth', 'ETH')]:
        for resource in packages.get(key, {}).get('resources', []):
            if f'wfp_food_prices_{country.lower()}.csv' not in resource['url']:
                continue
            payload = evidence.fetch(key + '_prices', resource['url'])
            if payload:
                d = csv(payload)
                current[country] = d
                wages.extend(wage_coverage(d, country, key))
                pairs.extend(pair_coverage(d, country, key, resource['url']))
    global_parts = []
    for resource in packages.get('wfp_global_current', {}).get('resources', []):
        match = re.search(r'wfp_food_prices_global_(201[5-9])\.csv$', resource['url'])
        if match:
            label = 'wfp_global_' + match.group(1)
            payload = evidence.fetch(label, resource['url'])
            if payload:
                d = csv(payload)
                country_column = next((x for x in ['iso3', 'countryiso3'] if x in d), None)
                if country_column is None:
                    outcomes[label] = {'status': 'schema_not_supported', 'columns': list(d)}
                    continue
                selected = d[d[country_column].isin(['YEM', 'ETH'])].copy()
                selected['_audit_country_iso3'] = selected[country_column]
                global_parts.append((label, resource['url'], selected))
                outcomes[label] = {'status': 'available', 'rows': len(d), 'target_rows': len(selected),
                                   'columns': list(d), 'country_column': country_column}
    if global_parts:
        selected = pd.concat([x[2] for x in global_parts], ignore_index=True)
        selected.to_csv(Path(output) / 'global_baseline_target_rows.csv.gz', index=False,
                        compression={'method': 'gzip', 'mtime': 0})
        for country in ['YEM', 'ETH']:
            local = selected[selected._audit_country_iso3.eq(country)].copy()
            wages.extend(wage_coverage(local, country, 'wfp_global_baseline'))
            pairs.extend(pair_coverage(local, country, 'wfp_global_baseline',
                                      'https://data.humdata.org/dataset/global-wfp-food-prices'))
            if country in current:
                key = ['date', 'market_id', 'commodity_id', 'commodity', 'unit', 'currency', 'pricetype', 'priceflag', 'price']
                current_keys = set(map(tuple, current[country][key].fillna('').astype(str).to_numpy()))
                difference = local[[tuple(r) not in current_keys for r in local[key].fillna('').astype(str).to_numpy()]]
                outcomes['global_difference_' + country] = {'candidate_quote_differences': len(difference),
                    'decision': 'Different rows, if any, require source-version and identity review; not imported.'}
                difference.to_csv(Path(output) / f'global_quote_differences_{country.lower()}.csv', index=False)
    for resource in packages.get('ipc', {}).get('resources', []):
        name = resource.get('name', '')
        if name in {'ipc_global_national_long.csv', 'ipc_global_level1_long.csv', 'ipc_global_area_long.csv'}:
            payload = evidence.fetch(name.removesuffix('.csv'), resource['url'])
            if payload:
                schemas.append(ipc_schema(csv(payload), name))
    legacy = packages.get('wfp_legacy', {}).get('resources', [])
    if len(legacy) == 1:
        payload = evidence.fetch('wfp_legacy_prices', legacy[0]['url'], max_bytes=300_000_000)
        if payload is None:
            outcomes['legacy_export'] = {'status': evidence.records['wfp_legacy_prices']['status'],
                'declared_resource_bytes': legacy[0].get('size'),
                'integration_status': 'Download unavailable; content not inspected. No absence-of-data conclusion.'}
        if payload:
            total, columns, selected = legacy_extract(payload)
            outcomes['legacy_export'] = {'rows': total, 'columns': columns, 'status': 'downloaded',
                                         'integration_status': 'not imported; source semantics require review'}
            # Preserve original identifiers/labels and all target-country rows as
            # a derived audit extract. It is never an active observation source.
            if 'adm0_name' in columns:
                selected.to_csv(Path(output) / 'legacy_target_country_rows.csv.gz', index=False,
                                compression={'method': 'gzip', 'mtime': 0})
                outcomes['legacy_export']['target_rows'] = len(selected)
                outcomes['legacy_export']['wage_summary_scope'] = 'Distinct quoted months across any market within each listed country/commodity/unit; not fixed-series eligibility. Legacy file lacks current-export priceflag.'
                outcomes['legacy_export']['wage_summary'] = []
                for identity, g in selected[selected.cm_name.str.contains('wage', case=False, na=False)].groupby(['adm0_name', 'cm_id', 'cm_name', 'um_name'], sort=True):
                    counts = {str(y): int(g[pd.to_numeric(g.mp_year).eq(y)].mp_month.nunique()) for y in range(2015, 2020)}
                    outcomes['legacy_export']['wage_summary'].append({'identity': list(identity), 'observations': len(g),
                        'baseline_months_by_year': counts, 'min_year': int(pd.to_numeric(g.mp_year).min()),
                        'max_year': int(pd.to_numeric(g.mp_year).max())})
    output = Path(output)
    pd.DataFrame(inventory).to_csv(output / 'resource_inventory.csv', index=False)
    pd.DataFrame(wages).to_csv(output / 'wage_coverage.csv', index=False)
    pd.DataFrame(pairs).to_csv(output / 'exact_pair_coverage.csv', index=False)
    write_json(output / 'ipc_schema_audit.json', schemas)
    write_json(output / 'discovery_results.json', outcomes)
    artifacts = ['resource_inventory.csv', 'wage_coverage.csv', 'exact_pair_coverage.csv',
                 'ipc_schema_audit.json', 'discovery_results.json']
    artifacts += [p.name for p in output.glob('global_*rows.csv.gz')]
    artifacts += [p.name for p in output.glob('global_quote_differences_*.csv')]
    if (output / 'legacy_target_country_rows.csv.gz').exists():
        artifacts.append('legacy_target_country_rows.csv.gz')
    write_json(output / 'audit_status.json', {
        'schema_version': 1, 'scope': 'Bounded public-source discovery; absence in searched sources is not universal absence.',
        'active_observations_mutated': False, 'eligibility_rules_changed': False,
        'failed_requests': sorted(k for k, v in evidence.records.items() if v['status'] != 'available'),
        'wfp_exact_series_checked': len(pairs),
        'wfp_current_baseline_eligible_series': sum(x['baseline_coverage_eligible'] for x in pairs
                                                  if x['source'] in {'wfp_yem', 'wfp_eth'}),
        'ipc_resources_checked': len(schemas), 'ipc_geography_certified': False,
        'outputs': {name: sha((output / name).read_bytes()) for name in sorted(artifacts)},
    })
    return outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--offline', action='store_true')
    mode.add_argument('--recover-legacy-ranges', action='store_true')
    args = parser.parse_args()
    if args.recover_legacy_ranges:
        recover_legacy_ranges(args.output)
        return
    run(args.output, args.offline)
    print(args.output / 'audit_status.json')


if __name__ == '__main__':
    main()
