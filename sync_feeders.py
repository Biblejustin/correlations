#!/usr/bin/env python3
"""Synchronize explicitly feeder-owned catalogue copies, preserving provenance.

Default: validate all required inputs, then copy changed bytes atomically.
--check: report source/target hashes and fail drift without writing anything.
Central curated wars, merged floods, NOAA, UCDP, and flare catalogues are outside
this allowlist and remain owned by their dedicated ingestion pipelines.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile


@dataclass(frozen=True)
class Feed:
    repository: str
    source: str
    target: str
    required: bool = True
    columns: tuple[str, ...] = ()


FEEDS = (
    Feed('volcanic-eruptions', 'volcanoes.csv', 'data/volcanoes.csv',
         columns=('year','vei')),
    Feed('tropical-cyclones', 'cyclones.csv', 'data/cyclones.csv',
         columns=('year','name','deaths_estimate')),
    Feed('droughts-tracking', 'droughts.csv', 'data/droughts.csv',
         columns=('start_year','end_year','deaths_estimate','people_affected')),
    Feed('pandemics-tracking', 'pandemics.csv', 'data/pandemics.csv',
         columns=('start_year','end_year','deaths_estimate')),
    Feed('astronomical-signs', 'eclipses.csv', 'data/astronomical_signs.csv',
         columns=('date','type')),
    Feed('famines-tracking', 'deaths-by-region-year.csv', 'data/famine_deaths_by_year.csv',
         columns=('entity','year','famine_deaths')),
    Feed('famines-tracking', 'famines-and-deaths.csv', 'data/famines_wpf.csv',
         columns=('entity','year','wpf_authoritative_mortality_estimate')),
    Feed('famines-tracking', 'historical_famines_pre1870.csv', 'data/famines_pre1870.csv',
         columns=('year_start','year_end','location','source_tradition')),
)

# Explicit optional snapshots support central reporting without changing the
# legacy global series. Directory topology identifies both source and analysis.
ISRAEL_FILES = {
    'israel-rain-agriculture': (
        'analysis_plan.json',
        'data/faostat_crop_measures.csv', 'data/faostat_crop_metadata.json',
        'data/kinneret_levels.csv', 'data/water_security_metadata.json',
        'data/water_covariates_reported.csv',
        'results/crop_rain_54.csv', 'results/crop_rain_manifest.json',
        'results/wheat_decomposition.csv', 'results/era_interaction.csv',
        'results/wheat_measure_identity.csv', 'results/prospective_wheat_model.json',
        'results/prospective_wheat_training.csv',
        'results/irrigation_sensitivity.csv', 'results/irrigation_sensitivity_plan.json',
        'climate_extension_plan.json', 'data/climate/source_manifest.json', 'data/climate/source_availability.json',
        'data/climate/cru_cy_4.08/monthly.csv', 'data/climate/cru_cy_4.08/annual_diagnostics.csv',
        'data/climate/cru_cy_4.10/monthly.csv', 'data/climate/cru_cy_4.10/annual_diagnostics.csv',
        'results/climate_monitor.json', 'results/climate_monitor.md',
        'results/climate_overlap_summary.json', 'results/climate_heat_irrigation_sensitivity.csv',
        'results/climate_aggregation_overlap_monthly.csv',
        'results/climate_version_overlap_monthly.csv', 'results/climate_version_overlap_annual.csv',
    ),
    'israel-pressure-disasters': (
        'data/test_results.csv', 'data/coverage.json', 'data/analysis_manifest.json',
    ),
}
ISRAEL_FEEDS = tuple(
    Feed(repository, source, f'data/israel_monitoring/{repository}/{source}', required=False)
    for repository, files in ISRAEL_FILES.items() for source in files
)
MANIFEST = 'data/feeder_sync_manifest.json'
PROTECTED_TARGETS = frozenset({
    'data/floods.csv','data/wars.csv','data/famines.csv','data/ucdp_prio_conflicts.csv',
    'data/noaa_significant_earthquakes.csv','data/noaa_volcanic_events.csv',
    'data/flares_xclass.csv','data/terrorism.csv','data/catalog_coverage.json',
})


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _within(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Path escapes declared root: {relative}')
    return path


def _sidecars(feed: Feed) -> tuple[Feed, ...]:
    """Support two explicit naming conventions; never glob arbitrary files."""
    if not feed.source.endswith('.csv'):
        return ()
    result = []
    for suffix in ('.coverage.json', '.metadata.json'):
        result.append(Feed(feed.repository,feed.source+suffix,feed.target+suffix,required=False))
        result.append(Feed(feed.repository,str(Path(feed.source).with_suffix(suffix)),
                           str(Path(feed.target).with_suffix(suffix)),required=False))
    return tuple(result)


def _validate(feed: Feed, content: bytes) -> None:
    if not content.strip():
        raise ValueError('Empty source file')
    if feed.source.endswith('.json'):
        parsed = json.loads(content)
        if feed.source.endswith('.coverage.json'):
            if not isinstance(parsed,dict) or not all(k in parsed for k in ('start_year','end_year')):
                raise ValueError('Coverage sidecar requires start_year and end_year')
            if int(parsed['end_year']) < int(parsed['start_year']):
                raise ValueError('Coverage end precedes start')
    elif feed.source.endswith('.csv'):
        reader = csv.reader(io.StringIO(content.decode('utf-8-sig')))
        header = next(reader, [])
        if not header or (feed.columns and not set(feed.columns).issubset(header)):
            raise ValueError(f'CSV missing required columns: {feed.columns}')
        # Header-only sources are not treated as successful replacement of an
        # established curated catalogue. Optional result tables may be empty.
        if feed.required and next(reader, None) is None:
            raise ValueError('Required catalogue has no data rows')


def _atomic_write_if_changed(path: Path, content: bytes) -> bool:
    if path.exists() and path.read_bytes() == content:
        return False
    path.parent.mkdir(parents=True,exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.'+path.name+'.',delete=False) as handle:
            temp = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temp.chmod(mode)
        temp.replace(path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return True


def sync(repo_root: Path, siblings_root: Path, *, check=False,
         feeds: tuple[Feed,...] = FEEDS + ISRAEL_FEEDS) -> dict:
    """Preflight a fixed allowlist, then atomically publish changed snapshots.

    No source or destination is removed. Missing formerly-present sidecars or
    snapshots are an error, rather than silently keeping stale metadata.
    """
    repo_root, siblings_root = Path(repo_root), Path(siblings_root)
    entries, planned, errors, seen = [], [], [], set()
    all_feeds = []
    for feed in feeds:
        all_feeds.append(feed)
        all_feeds.extend(_sidecars(feed))
    for feed in all_feeds:
        if feed.target in seen:
            errors.append(f'Duplicate mapped target: {feed.target}')
            continue
        seen.add(feed.target)
        if feed.target in PROTECTED_TARGETS:
            errors.append(f'Central-owned target is protected: {feed.target}')
            continue
        try:
            source = _within(siblings_root,feed.repository+'/'+feed.source)
            destination = _within(repo_root,feed.target)
            target_hash = _sha(destination.read_bytes()) if destination.exists() else None
            if not source.exists():
                if feed.required or destination.exists():
                    errors.append(f'Missing source: {feed.repository}/{feed.source}')
                # Optional sidecars never supplied do not clutter provenance.
                if feed.required or destination.exists() or feed in feeds:
                    entries.append(dict(repository=feed.repository,source=feed.source,target=feed.target,
                                        state='missing_source',source_sha256=None,target_sha256=target_hash))
                continue
            content = source.read_bytes()
            _validate(feed,content)
            source_hash = _sha(content)
            entries.append(dict(repository=feed.repository,source=feed.source,target=feed.target,
                                state='unchanged' if source_hash == target_hash else 'drift',
                                source_sha256=source_hash,target_sha256=target_hash,size_bytes=len(content)))
            planned.append((feed,destination,content))
        except (ValueError,OSError,UnicodeError) as exc:
            errors.append(f'{feed.repository}/{feed.source}: {exc}')
    # Source hashes are provenance; no timestamp means no false content change
    # when a weekly run sees identical bytes. Individual copy status is reported
    # to stdout only, not persisted into this stable manifest.
    manifest_files = []
    for entry in entries:
        if entry['source_sha256'] is None:
            continue
        manifest_files.append(dict(repository=entry['repository'],source_path=entry['source'],
                                   repository_url=f'https://github.com/Biblejustin/{entry["repository"]}',
                                   source_state='local_working_copy',
                                   target=entry['target'],sha256=entry['source_sha256'],size_bytes=entry['size_bytes']))
    manifest = dict(schema_version=1,policy='Explicit feeder-owned files only; byte-preserving atomic copy; no inferred coverage',
                    files=sorted(manifest_files,key=lambda x:x['target']))
    manifest_content=(json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode()
    manifest_path=_within(repo_root,MANIFEST)
    manifest_drift = not manifest_path.exists() or manifest_path.read_bytes() != manifest_content
    drift = sum(entry['state']=='drift' for entry in entries)
    report=dict(mode='check' if check else 'sync',ok=not errors and (not check or (drift==0 and not manifest_drift)),
                drift=drift,manifest_drift=manifest_drift,changed=0,errors=errors,files=entries)
    if errors or check:
        return report
    for feed,destination,content in planned:
        if _atomic_write_if_changed(destination,content):
            report['changed'] += 1
            entry = next(item for item in entries if item['target'] == feed.target)
            entry['state'] = 'copied'
            entry['target_sha256'] = entry['source_sha256']
    report['manifest_changed'] = _atomic_write_if_changed(manifest_path,manifest_content)
    return report


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--siblings-root',type=Path,default=None)
    parser.add_argument('--check',action='store_true',help='Fail drift or missing sources; never write files')
    parser.add_argument('--json',action='store_true',help='Print machine-readable hash/status report')
    args=parser.parse_args(argv)
    result=sync(args.repo_root,args.siblings_root or args.repo_root.parent,check=args.check)
    if args.json:
        print(json.dumps(result,indent=2,sort_keys=True))
    else:
        for entry in result['files']:
            if entry['source_sha256']:
                print(f'{entry["state"]}: {entry["target"]} sha256={entry["source_sha256"]}')
        for error in result['errors']:
            print('ERROR: '+error)
        print(f'{result["mode"]}: '+('OK' if result['ok'] else 'FAILED')+
              f'; changed={result["changed"]}; drift={result["drift"]}; manifest={MANIFEST}')
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
