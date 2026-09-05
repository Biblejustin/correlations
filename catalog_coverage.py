"""Declared catalogue scope; event thresholds never determine observation coverage.

A selected-event catalogue's zeros mean no *listed* events. They are not evidence
of complete surveillance or absence of disasters. That limitation travels in
Series.attrs['coverage']. Refreshers should write <source>.coverage.json with
source release bounds, even when a refresh contains no qualifying events.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

REGISTRY = Path(__file__).parent / 'data' / 'catalog_coverage.json'


def last_complete_year() -> int:
    return datetime.now(ZoneInfo('America/Chicago')).year - 1


def get_coverage(source_path, catalog_key=None, *, coverage=None) -> dict:
    """Explicit override > source sidecar > checked-in catalogue metadata.

    Bounds are never guessed from supplied event rows. Sidecar name appends
    '.coverage.json' to the entire filename, e.g. 'flares.csv.coverage.json'.
    """
    if coverage is not None:
        result = dict(coverage)
    else:
        sidecar = Path(str(source_path) + '.coverage.json')
        if sidecar.exists():
            result = json.loads(sidecar.read_text())
        else:
            registry = json.loads(REGISTRY.read_text())['catalogs']
            key = catalog_key or Path(source_path).name
            if key not in registry:
                raise ValueError(f'No declared coverage for {source_path!s}; supply coverage metadata')
            result = dict(registry[key])
    for key in ('start_year', 'end_year'):
        if key not in result or int(result[key]) != result[key]:
            raise ValueError(f'Coverage requires integer {key}')
        result[key] = int(result[key])
    if result['end_year'] < result['start_year']:
        raise ValueError('Coverage end precedes start')
    result.setdefault('complete_through_year', result['end_year'])
    result.setdefault('gap_years', [])
    result.setdefault('completeness', 'unknown')
    return result


def apply_coverage(series: pd.Series, source_path, catalog_key=None, *,
                   include_incomplete=False, coverage=None) -> pd.Series:
    """Mask both edges, declared gaps, and incomplete calendar years by default."""
    meta = get_coverage(source_path, catalog_key, coverage=coverage)
    result = series.astype(float).copy()
    high = meta['end_year']
    if not include_incomplete:
        high = min(high, int(meta['complete_through_year']), last_complete_year())
    years = np.asarray(result.index, dtype=int)
    missing = ((years < meta['start_year']) | (years > high)
               | np.isin(years, meta['gap_years']))
    result.iloc[np.flatnonzero(missing)] = np.nan
    result.attrs['coverage'] = meta
    result.attrs['include_incomplete'] = bool(include_incomplete)
    result.attrs['effective_coverage_end'] = high
    return result
