"""Read-only post-publication artifact contract checks in the pinned environment."""
from __future__ import annotations
import argparse
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(workspace, started_at):
    workspace = Path(workspace).resolve()
    base = workspace/'correlations'
    sys.path.insert(0, str(base))
    import pandas as pd
    from monitoring import trade_sources, economic_sources, climate_indices
    from monitoring.analysis import load_observations, build_annual_panel
    from monitoring.extensions import _fingerprint, load_global_series
    import sync_feeders
    from weekly_update import fetch_steps
    from run_suite import SCRIPTS
    read = lambda path: json.loads(Path(path).read_text())
    run = read(base/'results/refresh_run.json')
    if not run['success'] or run['fetch_skipped'] or run.get('fetch_only'):
        raise ValueError('Not a successful full source refresh')
    if pd.Timestamp(run['generated_at']) < pd.Timestamp(started_at):
        raise ValueError('Stale refresh receipt')
    names = [row['stage'] for row in run['stages']]
    required = {'regression_tests', 'sync_feeders', 'predictions_scorecard', 'refresh_report', 'dashboard'} | set(SCRIPTS) | {row[0] for row in fetch_steps()}
    if not required <= set(names) or len(names) != len(set(names)) or any(row['status'] != 'passed' for row in run['stages']):
        raise ValueError('Incomplete or failed refresh stages')
    source_data = {}
    for name, module in [('shipping', trade_sources), ('economic', economic_sources), ('climate', climate_indices)]:
        tables, manifest = module.load_snapshot(replay=True) if name == 'shipping' else module.load_snapshot()
        source_data[name] = (module.ROOT, tables, manifest)
    root, tables, cm = source_data['climate']
    raw = {name: gzip.decompress((root/row['path']).read_bytes()) for name, row in cm['inputs'].items()}
    rebuilt = climate_indices.build_tables(raw, cm['as_of_utc'])
    payloads = {name: frame.to_csv(index=False).encode() for name, frame in rebuilt.items()}
    for name, payload in payloads.items():
        if payload != (root/cm['outputs'][name]['path']).read_bytes():
            raise ValueError('Climate raw replay disagrees with normalized snapshot')
    identity = hashlib.sha256(b''.join(name.encode()+payloads[name] for name in sorted(payloads))).hexdigest()
    if identity != cm['snapshot_id']:
        raise ValueError('Climate snapshot identity mismatch')
    output = base/'results/monitoring'
    tm, xm = read(output/'trade/trade_manifest.json'), read(output/'extensions/extensions_manifest.json')
    checked = 0
    for name, record in tm['outputs'].items():
        path = output/'trade'/name
        if sha(path) != record['sha256'] or len(pd.read_csv(path)) != record['rows']:
            raise ValueError('Trade artifact hash/count mismatch: '+name)
        checked += 1
    for name, key in [('trade_report.md', 'report_sha256'), ('shipping_transit.png', 'plot_sha256')]:
        if sha(output/'trade'/name) != tm[key]:
            raise ValueError('Trade report/plot hash mismatch')
        checked += 1
    for name, expected in xm['outputs'].items():
        if sha(output/'extensions'/name) != expected:
            raise ValueError('Extension artifact hash mismatch: '+name)
        checked += 1
    for name, (root, _, manifest) in source_data.items():
        if tm['source_manifests'][name] != {'sha256': sha(root/'manifest.json'), 'snapshot_id': manifest['snapshot_id']}:
            raise ValueError('Trade source binding mismatch: '+name)
    if tm['plan_sha256'] != sha(base/'monitoring/trade_plan.json') or xm['extension_plan_sha256'] != sha(base/'monitoring/extension_plan.json'):
        raise ValueError('Analysis plan binding mismatch')
    if xm['climate_snapshot_id'] != cm['snapshot_id'] or xm['climate_manifest_sha256'] != sha(source_data['climate'][0]/'manifest.json'):
        raise ValueError('Extension climate source binding mismatch')
    observations = load_observations()
    panel = build_annual_panel(observations, as_of=xm['report_date'])
    if tm['observation_fingerprint'] != _fingerprint(observations) or xm['observation_fingerprint'] != _fingerprint(observations) or xm['annual_panel_fingerprint'] != _fingerprint(panel):
        raise ValueError('Analysis input fingerprints disagree')
    series = load_global_series(end_year=pd.Timestamp(xm['report_date']).year-1)
    if xm['global_series_fingerprints'] != {name: _fingerprint(value[0] if isinstance(value, tuple) else value) for name, value in series.items()}:
        raise ValueError('Original global-loader input fingerprint changed')
    fit_counts = {}
    for label, filename, family in [('trade', 'trade/trade_food_tests.csv', tm['planned_fits']), ('global_climate', 'extensions/global_climate_sensitivity.csv', xm['global_planned_fits']), ('regional_climate', 'extensions/regional_climate_sensitivity.csv', xm['regional_planned_fits'])]:
        frame = pd.read_csv(output/filename)
        eligible = frame.status.eq('eligible')
        if len(frame) != family or not frame.family_size.eq(family).all() or (frame.reject_fdr & ~eligible).any() or not frame.loc[~eligible, 'q_family'].eq(1).all():
            raise ValueError('Fixed family/eligibility inconsistency: '+label)
        fit_counts[label] = {'planned': len(frame), 'eligible': int(eligible.sum()), 'passing': int(frame.reject_fdr.sum())}
    result = sync_feeders.sync(base, workspace, check=True)
    if not result['ok']:
        raise ValueError('Feeder sync drift: '+json.dumps({key: result[key] for key in ['drift', 'manifest_drift', 'errors']}))
    # Sync checks NASA artifact hashes and source/code/plan bindings after the normal offline replay stage.
    nasa = read(workspace/'astronomical-signs/data/eclipses/validation.json')
    if nasa['status'] != 'passed':
        raise ValueError('Eclipse reference validation failed')
    return {'status': 'passed', 'refresh_stages': len(names), 'artifact_hashes': checked, 'fit_counts': fit_counts,
            'snapshot_ids': {name: value[2]['snapshot_id'] for name, value in source_data.items()},
            'eclipse_checks': nasa['check_count'], 'sync_drift': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--started-at', required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.workspace, args.started_at), sort_keys=True, allow_nan=False))
