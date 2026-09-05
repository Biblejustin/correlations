"""Persist SWPC observations and explicit sampled intervals, including quiet weeks."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import pandas as pd

from source_tracking import write_json_if_changed

SWPC_URL = 'https://services.swpc.noaa.gov/json/goes/primary/xray-flares-7-day.json'


def ingest_recent_flares(raw_path: Path, data_dir: Path, fetched_at: str | None = None) -> dict:
    rows = json.loads(raw_path.read_text())
    if not isinstance(rows, list):
        raise ValueError('SWPC payload must be an event array')
    stamp = pd.Timestamp(fetched_at or dt.datetime.now(dt.timezone.utc).isoformat())
    stamp = stamp.tz_localize('UTC') if stamp.tzinfo is None else stamp.tz_convert('UTC')
    records = []
    response_ids = set()
    for row in rows:
        if not isinstance(row, dict) or 'max_class' not in row or 'begin_time' not in row:
            raise ValueError('Unexpected SWPC flare schema; keeping raw payload')
        begin = pd.Timestamp(row['begin_time'])
        if begin.tzinfo is None:
            raise ValueError('SWPC times must carry UTC timezone')
        begin = begin.tz_convert('UTC')
        response_ids.add('swpc:' + begin.isoformat())
        if not row.get('max_time') or not row.get('max_class'):
            continue  # unfinished event; next successful poll can supply its peak
        peak = pd.Timestamp(row['max_time'])
        if begin.tzinfo is None or peak.tzinfo is None:
            raise ValueError('SWPC times must carry UTC timezone')
        peak = peak.tz_convert('UTC')
        if peak < begin or begin > stamp:
            raise ValueError('SWPC event timestamps outside valid ordering')
        records.append({'event_id': 'swpc:' + begin.isoformat(), 'begin_time': begin.isoformat(),
                        'peak_time': peak.isoformat(), 'date': peak.date().isoformat(),
                        'class': row['max_class'], 'satellite': row.get('satellite'),
                        'source_url': SWPC_URL})
    target = data_dir / 'flares_swpc.csv'
    old = pd.read_csv(target) if target.exists() else pd.DataFrame()
    withdrawn_ids = set()
    if len(old):
        begins = pd.to_datetime(old.begin_time, utc=True)
        inside = begins.between(stamp-pd.Timedelta(days=7), stamp)
        withdrawn_ids = set(old.loc[inside & ~old.event_id.isin(response_ids), 'event_id'])
        if withdrawn_ids:
            audit_path = data_dir / 'flares_swpc_withdrawn.csv'
            audit_old = pd.read_csv(audit_path) if audit_path.exists() else pd.DataFrame()
            withdrawn = old[old.event_id.isin(withdrawn_ids)].assign(withdrawn_at=stamp.isoformat())
            audit = pd.concat([audit_old, withdrawn], ignore_index=True).drop_duplicates(['event_id','withdrawn_at'])
            temp = audit_path.with_suffix('.csv.tmp'); temp.write_text(audit.to_csv(index=False)); temp.replace(audit_path)
            old = old[~old.event_id.isin(withdrawn_ids)]
    fresh = pd.DataFrame(records, columns=['event_id','begin_time','peak_time','date','class','satellite','source_url'])
    merged = pd.concat([old, fresh], ignore_index=True).drop_duplicates('event_id', keep='last')
    merged = merged.sort_values(['begin_time', 'event_id'])
    data_dir.mkdir(parents=True, exist_ok=True)
    content = merged.to_csv(index=False)
    if not target.exists() or target.read_text() != content:
        temp = target.with_suffix('.csv.tmp'); temp.write_text(content); temp.replace(target)
    # Merge X flares into legacy selection without erasing historical annotations.
    legacy_path = data_dir / 'flares_xclass.csv'
    legacy = pd.read_csv(legacy_path).to_dict('records') if legacy_path.exists() else []
    legacy = [r for r in legacy if r.get('event_id') not in withdrawn_ids]
    for row in records:
        match = next((r for r in legacy if r.get('event_id') == row['event_id']), None)
        if not str(row['class']).startswith('X'):
            if match is not None:
                legacy.remove(match)  # revision can downgrade an earlier X-class observation
            continue
        if match is None:
            match = next((r for r in legacy if str(r.get('date')) == row['date']
                          and r.get('class') == row['class'] and pd.isna(r.get('event_id'))), None)
        if match is None:
            match = {'notes': 'SWPC event; complete only inside recorded observation intervals'}
            legacy.append(match)
        match.update({k: row[k] for k in ['date','class','event_id','peak_time']})
        match['sources'] = SWPC_URL
    if legacy or legacy_path.exists():
        columns = list(pd.read_csv(legacy_path, nrows=0).columns) if legacy_path.exists() else ['date','class','event_id','peak_time','sources','notes']
        frame = pd.DataFrame(legacy, columns=columns if not legacy else None).sort_values(['date','class'])
        content = frame.to_csv(index=False)
        if not legacy_path.exists() or legacy_path.read_text() != content:
            temp = legacy_path.with_suffix('.csv.tmp'); temp.write_text(content); temp.replace(legacy_path)
    manifest_path = data_dir / 'swpc_observation_intervals.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'schema_version': 1, 'intervals': []}
    # Endpoint is rolling seven days, not an archive. Never fill between missed polls.
    manifest['intervals'].append({'start': (stamp-pd.Timedelta(days=7)).isoformat(), 'end': stamp.isoformat()})
    intervals = sorted((pd.Timestamp(x['start']), pd.Timestamp(x['end'])) for x in manifest['intervals'])
    union = []
    for start, end in intervals:
        if union and start <= union[-1][1]:
            union[-1] = (union[-1][0], max(end, union[-1][1]))
        else:
            union.append((start,end))
    manifest.update({'source_url': SWPC_URL, 'fetched_at': stamp.isoformat(),
                     'payload_sha256': hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                     'intervals': [{'start': a.isoformat(),'end': b.isoformat()} for a,b in union],
                     'notes': 'No coverage claimed between intervals; historical curated list is incomplete.'})
    write_json_if_changed(manifest_path, manifest)
    archive = data_dir.parent / '.cache/swpc' / (manifest['payload_sha256'] + '.json')
    archive.parent.mkdir(parents=True,exist_ok=True)
    if not archive.exists():
        archive.write_bytes(raw_path.read_bytes())
    raw_path.unlink()
    return {'events_in_response': len(records), 'stored_events': len(merged), 'coverage_intervals': len(union), 'withdrawn_in_response_window': len(withdrawn_ids)}
