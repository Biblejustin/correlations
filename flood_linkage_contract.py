"""Validate bounded flood corrections before replacing any canonical identity.

Raw rows remain unchanged. Missing/stale evidence for the managed central catalog
is an error; callers can explicitly request the legacy baseline for sensitivity.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import pandas as pd

MANAGED_CATALOG = Path(__file__).resolve().parent / 'data/floods.csv'


def _digest(content):
    return hashlib.sha256(content).hexdigest()


def _row_digest(row):
    return _digest(json.dumps(row, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode())


def legacy_identities(raw):
    identities = pd.Series(['row:' + str(i) for i in range(len(raw))], index=raw.index)
    if 'match_group_id' not in raw:
        return identities
    grouped = raw['match_group_id'].notna()
    identities.loc[grouped] = 'match:' + raw.loc[grouped, 'match_group_id'].astype(str)
    source_ids = raw.get('source_id', pd.Series('', index=raw.index)).fillna('').astype(str)
    identified = ~grouped & source_ids.ne('')
    sources = raw.get('source', pd.Series('', index=raw.index)).fillna('').astype(str)
    identities.loc[identified] = sources.loc[identified] + ':' + source_ids.loc[identified]
    return identities


def validate_contract(catalog_path, contract_path=None):
    path = Path(catalog_path)
    sidecar = Path(contract_path) if contract_path is not None else Path(str(path) + '.linkage.json')
    if not sidecar.exists():
        if contract_path is not None or path.resolve() == MANAGED_CATALOG.resolve():
            raise ValueError(f'Required flood linkage contract missing: {sidecar}')
        return {}, dict(status='legacy_unreviewed', corrected_groups=0, corrected_source_rows=0)
    try:
        contract_bytes = sidecar.read_bytes()
        contract = json.loads(contract_bytes)
        if contract.get('schema_version') != 1:
            raise ValueError('Unsupported flood linkage contract schema')
        content = path.read_bytes()
        if _digest(content) != contract['catalog_sha256']:
            raise ValueError('Flood source hash changed; correction ledger requires renewed source review')
        records = list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
        if len(records) != contract['raw_rows']:
            raise ValueError('Flood source row count disagrees with correction contract')
        lookup = {(row['source'], row['source_id']): row for row in records}
        if len(lookup) != len(records):
            raise ValueError('Flood correction contract requires unique stable source identities')
        for relative, expected in contract['evidence_sha256'].items():
            evidence = sidecar.parent / relative
            if not evidence.resolve().is_relative_to(sidecar.parent.resolve()):
                raise ValueError('Flood evidence path escapes contract directory')
            if not evidence.is_file() or _digest(evidence.read_bytes()) != expected:
                raise ValueError(f'Flood publisher evidence missing or hash mismatch: {relative}')
        if not contract['evidence_sha256']:
            raise ValueError('Flood correction contract requires publisher evidence')
        ledger_name = contract['publisher_link_ledger']
        if ledger_name not in contract['evidence_sha256']:
            raise ValueError('Publisher link ledger is not bound to an evidence hash')
        with (sidecar.parent / ledger_name).open(newline='') as handle:
            publisher_links = list(csv.DictReader(handle))
        accepted_edges = {(row['dfo_id'], row['emdat_event_id']) for row in publisher_links if row['status'] == 'accepted'}
        assignments = {}
        seen_groups = set()
        seen_targets = set()
        for correction in contract['corrections']:
            group_id = correction['legacy_match_group_id']
            if group_id in seen_groups:
                raise ValueError('Flood correction contract repeats a legacy group')
            seen_groups.add(group_id)
            members = {(row['source'], row['source_id']) for row in records
                       if row['match_group_id'] and str(float(row['match_group_id'])) == group_id}
            supplied = {(row['source'], row['source_id']) for row in correction['records']}
            if not members or supplied != members or len(supplied) != len(correction['records']):
                raise ValueError(f'Flood correction must preserve every member of group {group_id} exactly once')
            targets = set()
            for row in correction['records']:
                key = (row['source'], row['source_id'])
                if key in assignments or _row_digest(lookup[key]) != row['row_sha256']:
                    raise ValueError(f'Flood stable source record changed or repeated: {key}')
                target = row['canonical_event_id']
                if not target.startswith(f'split:{group_id}:emdat:'):
                    raise ValueError('Flood correction target must remain within its reviewed legacy group')
                if row['source'] == 'DFO':
                    event_id = target.split(':emdat:', 1)[1]
                    method = correction['method']
                    if method == 'publisher_id_and_temporal_separation':
                        if (row['source_id'], event_id) not in accepted_edges:
                            raise ValueError('DFO correction contradicts the accepted publisher link ledger')
                    elif method == 'reviewed_date_geography_split':
                        if group_id != '3.0' or row['source_id'] != 'DFO-5516' or event_id != '2024-0098':
                            raise ValueError('Unknown manually reviewed flood linkage exception')
                    else:
                        raise ValueError('Unknown flood correction evidence method')
                assignments[key] = target
                targets.add(target)
            if len(targets) < 2 or targets & seen_targets:
                raise ValueError('Flood correction must split a group without joining other groups')
            # Every output unit must retain an actual publisher event identity.
            for target in targets:
                emdat_ids = {row['source_id'].rsplit('-', 1)[0] for row in correction['records']
                             if row['source'] == 'EM-DAT' and row['canonical_event_id'] == target}
                if emdat_ids != {target.split(':emdat:', 1)[1]}:
                    raise ValueError('Flood correction combines or invents EM-DAT event identities')
            seen_targets.update(targets)
        counts = contract['counts']
        if (sum(row['status'] == 'accepted' for row in publisher_links) != counts['accepted_publisher_links']
                or sum(row['status'] == 'rejected' for row in publisher_links) != counts['rejected_publisher_links']):
            raise ValueError('Publisher link status counts disagree with correction contract')
        if len(seen_groups) != counts['corrected_legacy_groups'] or len(assignments) != counts['corrected_source_rows']:
            raise ValueError('Flood correction counts disagree with assignment ledger')
        return assignments, dict(status='reviewed_corrections_applied', corrected_groups=len(seen_groups),
                                 corrected_source_rows=len(assignments), contract_sha256=_digest(contract_bytes),
                                 catalog_sha256=contract['catalog_sha256'], publisher_workbook_sha256=contract['publisher_workbook_sha256'],
                                 accepted_publisher_links=counts['accepted_publisher_links'],
                                 rejected_publisher_links=counts['rejected_publisher_links'],
                                 unit='reviewed catalog event identities; physical-disaster independence not established')
    except (AttributeError, KeyError, TypeError, json.JSONDecodeError, UnicodeError, OSError) as error:
        raise ValueError(f'Invalid flood linkage contract {sidecar}: {error}') from error


def canonical_identities(raw, catalog_path, *, apply_corrections=True, contract_path=None):
    identities = legacy_identities(raw)
    if not apply_corrections:
        return identities, dict(status='explicit_legacy_sensitivity', corrected_groups=0, corrected_source_rows=0)
    assignments, metadata = validate_contract(catalog_path, contract_path)
    if assignments:
        for index, row in raw.iterrows():
            target = assignments.get((str(row['source']), str(row['source_id'])))
            if target is not None:
                identities.loc[index] = target
    return identities, metadata
