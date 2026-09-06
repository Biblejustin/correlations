import gzip
import json

import pandas as pd
import pytest

from monitoring.recovery_audit import Evidence, ipc_schema, pair_coverage, recover_legacy_ranges, sha, wage_coverage


def quote(month, commodity='Wage (non-qualified labour)', commodity_id='325',
          market='10', currency='YER', price='1000', flag='actual', unit='Day'):
    return dict(date=month + '-15', commodity=commodity, commodity_id=commodity_id,
                market_id=market, currency=currency, price=price, priceflag=flag,
                unit=unit, pricetype='Retail')


def test_exact_frozen_baseline_cannot_fill_missing_year_with_more_other_months():
    rows = []
    for year in range(2016, 2020):
        for month in range(1, 13):
            period = f'{year}-{month:02d}'
            rows += [quote(period), quote(period, 'Wheat flour', '15', price='100', unit='KG')]
    result = pair_coverage(pd.DataFrame(rows), 'YEM', 'fixture', 'https://example.org/wfp.csv')
    assert len(result) == 1
    assert result[0]['baseline_months'] == 48
    assert json.loads(result[0]['baseline_year_counts'])['2015'] == 0
    assert result[0]['baseline_coverage_eligible'] is False


def test_wage_audit_preserves_semantic_and_priceflag_differences():
    rows = [quote('2015-08'), quote('2016-01', commodity='Wage (casual labour)'),
            quote('2015-09', flag='aggregate')]
    result = wage_coverage(pd.DataFrame(rows), 'ETH', 'fixture')
    assert len(result) == 3
    observed = [r for r in result if r['commodity'] == 'Wage (non-qualified labour)' and r['priceflag'] == 'actual']
    assert observed[0]['months_2015'] == 1
    assert observed[0]['months_2016'] == 0


def test_schema_names_cannot_certify_geography_or_create_ids():
    d = pd.DataFrame({'Country': ['ETH'], 'Area': ['Example'], 'Analysis ID': ['1'], 'geometry': ['unknown']})
    result = ipc_schema(d, 'fixture.csv')
    assert result['candidate_identifier_columns'] == ['Analysis ID']
    assert result['candidate_geometry_columns'] == ['geometry']
    assert result['identity_or_geography_certified'] is False


def test_evidence_failure_stays_unavailable_and_damaged_archive_rejected(tmp_path):
    payload = b'actual source payload'
    (tmp_path / 'raw').mkdir()
    path = 'raw/' + sha(payload) + '.gz'
    (tmp_path / path).write_bytes(gzip.compress(payload, mtime=0))
    records = {'ok': {'status': 'available', 'url': 'https://example.org/ok', 'path': path, 'sha256': sha(payload)},
               'failed': {'status': 'http_error', 'url': 'https://example.org/fail', 'http_status': 403}}
    (tmp_path / 'requests.json').write_text(json.dumps(records))
    evidence = Evidence(tmp_path, offline=True)
    assert evidence.fetch('failed', records['failed']['url']) is None
    assert evidence.fetch('ok', records['ok']['url']) == payload
    with pytest.raises(ValueError, match='matching archived'):
        evidence.fetch('ok', 'https://example.org/different')
    (tmp_path / path).write_bytes(gzip.compress(b'replaced', mtime=0))
    with pytest.raises(ValueError, match='Damaged'):
        evidence.fetch('ok', records['ok']['url'])


@pytest.mark.parametrize('mixed_version', [False, True])
def test_legacy_ranges_require_complete_bytes_and_common_source_version(tmp_path, monkeypatch, mixed_version):
    raw = b'Complete archived source, including every byte.'
    url = 'https://example.org/archive.csv'
    meta = json.dumps({'result': {'resources': [{'url': url, 'size': len(raw)}]}}).encode()
    (tmp_path / 'raw').mkdir()
    path = 'raw/' + sha(meta) + '.gz'
    (tmp_path / path).write_bytes(gzip.compress(meta, mtime=0))
    records = {'wfp_legacy_metadata': {'url': 'https://example.org/meta', 'status': 'available', 'path': path, 'sha256': sha(meta)},
               'wfp_legacy_prices': {'url': url, 'status': 'request_failed', 'error': 'fixture bulk timeout'}}
    (tmp_path / 'requests.json').write_text(json.dumps(records))

    class Response:
        def __init__(self, start, end):
            self.status_code = 206
            self.headers = {'Content-Range': f'bytes {start}-{end}/{len(raw)}',
                            'ETag': '"second"' if mixed_version and start else '"first"',
                            'Last-Modified': 'Wed, 01 Jan 2025 00:00:00 GMT'}
            self.payload = raw[start:end+1]
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def iter_content(self, size): yield self.payload

    def get(requested, **kwargs):
        assert requested == url
        start, end = map(int, kwargs['headers']['Range'].removeprefix('bytes=').split('-'))
        return Response(start, end)

    monkeypatch.setattr('monitoring.recovery_audit.requests.get', get)
    if mixed_version:
        with pytest.raises(ValueError, match='changed between ranges'):
            recover_legacy_ranges(tmp_path, chunk_bytes=10)
        assert Evidence(tmp_path, offline=True).read('wfp_legacy_prices') is None
    else:
        record = recover_legacy_ranges(tmp_path, chunk_bytes=10)
        assert record['sha256'] == sha(raw)
        assert Evidence(tmp_path, offline=True).read('wfp_legacy_prices') == raw
        # Resume verifies stored chunks and does not require a second download.
        monkeypatch.setattr('monitoring.recovery_audit.requests.get', lambda *a, **k: pytest.fail('unexpected network'))
        assert recover_legacy_ranges(tmp_path, chunk_bytes=10)['sha256'] == sha(raw)
