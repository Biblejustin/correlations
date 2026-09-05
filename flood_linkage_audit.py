"""Reproduce flood linkage ambiguities without inventing or replacing source links.

Outputs preserve the existing canonical selection and expose every member of a
flagged group. Quarantine means needs source adjudication, not proven mismatch.
The unflagged subset is only a sensitivity input; omitted events are unknown,
and must never be converted to zero or claimed as a complete catalog.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

import pandas as pd

from correlate_events import load_canonical_flood_events
from source_tracking import file_digest, write_json_if_changed

BASE = Path(__file__).resolve().parent
RULES = {
    'multiple_emdat_event_ids': 'Group contains different EM-DAT year-number event identities; country suffixes alone do not trigger this rule.',
    'multiple_dfo_event_ids': 'Group contains different DFO source event IDs.',
    'multiple_other_source_ids': 'A different source supplies multiple distinct event IDs in one group.',
    'source_identity_in_multiple_groups': 'Same source and source ID appear in more than one canonical group.',
    'incompatible_date_intervals': 'Valid supplied intervals have no common date; geographic phases can differ, so manual source review is required.',
    'invalid_date_interval': 'At least one supplied end date precedes its start date.',
    'missing_start_date': 'At least one source row has no parseable start date.',
    'imprecise_start_date': 'At least one source row lacks an explicit day or declares coarser date precision.',
    'missing_source_identity': 'At least one source row lacks a source name or stable source ID.',
}


def _joined(values):
    return json.dumps(sorted({str(value) for value in values if pd.notna(value) and str(value)}), separators=(',', ':'))


def _group_ids(raw):
    """Reproduce the loader's identity convention; selection stays in the loader."""
    grouped = raw['match_group_id'].notna()
    identities = pd.Series(['row:' + str(i) for i in range(len(raw))], index=raw.index)
    identities.loc[grouped] = 'match:' + raw.loc[grouped, 'match_group_id'].astype(str)
    source_ids = raw['source_id'].fillna('').astype(str)
    identified = ~grouped & source_ids.ne('')
    identities.loc[identified] = raw.loc[identified, 'source'].fillna('').astype(str) + ':' + source_ids.loc[identified]
    return identities


def audit_catalog(path):
    """Return deterministic evidence frames and a manifest; never mutate input."""
    path = Path(path)
    raw = pd.read_csv(path, low_memory=False)
    required = {'source', 'source_id', 'match_group_id', 'start_date', 'end_date', 'deaths'}
    if required - set(raw):
        raise ValueError(f'Missing flood columns: {sorted(required - set(raw))}')
    if raw.empty:
        raise ValueError('Flood catalog is empty')
    canonical = load_canonical_flood_events(str(path))
    raw['source_record_number'] = range(1, len(raw) + 1)
    raw['canonical_event_id'] = _group_ids(raw)
    if set(raw['canonical_event_id']) != set(canonical['canonical_event_id']):
        raise ValueError('Audit identity rules diverged from the canonical loader')
    raw['_start'] = pd.to_datetime(raw['start_date'], errors='coerce', format='mixed')
    raw['_end'] = pd.to_datetime(raw['end_date'], errors='coerce', format='mixed').fillna(raw['_start'])
    raw['_deaths'] = pd.to_numeric(raw['deaths'], errors='coerce')
    stable = raw.dropna(subset=['source', 'source_id'])
    repeated = stable.groupby(['source', 'source_id'])['canonical_event_id'].nunique()
    reused = set(repeated[repeated > 1].index)
    selected = canonical.set_index('canonical_event_id')
    groups = []
    for identity, rows in raw.groupby('canonical_event_id', sort=True):
        flags = []
        event_ids = {}
        for source, source_rows in rows.groupby('source', dropna=False, sort=True):
            ids = set(source_rows['source_id'].dropna().astype(str))
            if source == 'EM-DAT':
                ids = {re.sub(r'^([0-9]{4}-[0-9]+)-[A-Z]{3}$', r'\1', value) for value in ids}
                if len(ids) > 1:
                    flags.append('multiple_emdat_event_ids')
            elif source == 'DFO' and len(ids) > 1:
                flags.append('multiple_dfo_event_ids')
            elif source != 'DFO' and len(ids) > 1:
                flags.append('multiple_other_source_ids')
            event_ids[str(source)] = sorted(ids)
        if any((row.source, row.source_id) in reused for row in rows.itertuples()):
            flags.append('source_identity_in_multiple_groups')
        if (rows['_end'] < rows['_start']).any():
            flags.append('invalid_date_interval')
        if rows['_start'].isna().any():
            flags.append('missing_start_date')
        exact = rows['start_date'].astype(str).str.match(r'^\d{4}-\d{2}-\d{2}(?:$|[T ])')
        if 'date_precision' in rows:
            exact &= rows['date_precision'].fillna('day').astype(str).str.lower().isin(['day', 'exact', 'daily'])
        if not exact.all():
            flags.append('imprecise_start_date')
        valid = rows[rows['_start'].notna() & rows['_end'].ge(rows['_start'])]
        if len(valid) > 1 and valid['_start'].max() > valid['_end'].min():
            flags.append('incompatible_date_intervals')
        if rows[['source', 'source_id']].isna().any().any() or rows[['source', 'source_id']].fillna('').eq('').any().any():
            flags.append('missing_source_identity')
        chosen = selected.loc[identity]
        deaths = rows['_deaths'].dropna()
        selected_deaths = chosen['deaths']
        low, high = (float(deaths.min()), float(deaths.max())) if len(deaths) else (None, None)
        groups.append(dict(
            canonical_event_id=identity, review_required=bool(flags), review_flags=';'.join(sorted(set(flags))),
            source_rows=len(rows), source_record_numbers=json.dumps(sorted(rows['source_record_number'].astype(int).tolist()), separators=(',', ':')),
            sources=_joined(rows['source']), source_event_ids=json.dumps(event_ids, sort_keys=True, separators=(',', ':')),
            countries=_joined(rows.get('country', [])), iso_codes=_joined(rows.get('iso', [])),
            raw_start_dates=_joined(rows['start_date']), raw_end_dates=_joined(rows['end_date']),
            selected_source=chosen['source'], selected_source_id=chosen['source_id'],
            selected_start_date=chosen['start_date'], selected_end_date=chosen['end_date'],
            selected_deaths=selected_deaths, deaths_min_reported=low, deaths_max_reported=high,
            unknown_death_rows=int(rows['_deaths'].isna().sum()), mortality_disagreement=bool(len(deaths) and low != high),
            reported_tolls_straddle_1000=bool(len(deaths) and low < 1000 <= high),
            selected_below_1000_other_report_at_least_1000=bool(pd.notna(selected_deaths) and selected_deaths < 1000 and high is not None and high >= 1000),
        ))
    groups = pd.DataFrame(groups)
    annotation = groups.set_index('canonical_event_id')[['review_required', 'review_flags']]
    members = raw.drop(columns=['_start', '_end', '_deaths']).join(annotation, on='canonical_event_id')
    canonical = canonical.join(annotation, on='canonical_event_id')
    canonical = canonical.sort_values('canonical_event_id', kind='stable').reset_index(drop=True)
    quarantine = members[members['review_required']].sort_values(['canonical_event_id', 'source_record_number'], kind='stable')
    unflagged = canonical[~canonical['review_required']].copy()
    rule_counts = {rule: int(groups['review_flags'].str.split(';').map(lambda flags: rule in flags).sum()) for rule in RULES}
    manifest = dict(
        schema_version=1, source_filename=path.name, source_sha256=file_digest(path),
        source_repository='https://github.com/Biblejustin/flood-data',
        canonical_policy=canonical.attrs.get('deduplication', 'EM-DAT before DFO; stable source ID/date/row tie; before filters'),
        rules=RULES, counts=dict(raw_rows=len(raw), canonical_events=len(canonical),
                                review_required_groups=int(groups['review_required'].sum()), quarantined_source_rows=len(quarantine),
                                unflagged_sensitivity_events=len(unflagged), mortality_disagreement_groups=int(groups['mortality_disagreement'].sum()),
                                reported_tolls_straddle_1000_groups=int(groups['reported_tolls_straddle_1000'].sum())),
        rule_counts=rule_counts,
        limitations=[
            'Flags are reproducible evidence for source adjudication, not proof that linked records describe different disasters.',
            'Country rows sharing an EM-DAT year-number are not flagged as different EM-DAT event identities merely because country suffixes differ.',
            'Neither the raw input nor the analysis loader is modified; canonical selection remains provisional.',
            'Unflagged sensitivity events are an incomplete diagnostic subset. Excluded or unknown records must not be treated as zero.',
            'Source record numbers are one-based CSV data-record positions, excluding the header; quoted multiline fields can span physical lines.',
            'Mortality reports can refer to different geographic scopes; no totals are added or invented during linkage review.',
        ],
    )
    return dict(groups=groups, quarantine_rows=quarantine, canonical_events=canonical,
                canonical_unflagged_sensitivity=unflagged), manifest


def write_audit(source, output):
    frames, manifest = audit_catalog(source)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, frame in frames.items():
        content = frame.to_csv(index=False, lineterminator='\n').encode()
        dest = output / (name + '.csv')
        if not dest.exists() or dest.read_bytes() != content:
            temp = dest.with_name(dest.name + '.tmp')
            temp.write_bytes(content)
            temp.replace(dest)
        hashes[dest.name] = hashlib.sha256(content).hexdigest()
    manifest['output_sha256'] = hashes
    write_json_if_changed(output / 'manifest.json', manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=BASE / 'data/floods.csv')
    parser.add_argument('--output', type=Path, default=BASE / 'data/diagnostics/flood_linkage')
    args = parser.parse_args(argv)
    result = write_audit(args.input, args.output)
    print(json.dumps(result['counts'], indent=2))
    print('Audit complete. Flagged groups require source adjudication; analysis loader remains unchanged.')


if __name__ == '__main__':
    main()
