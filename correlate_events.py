"""
Shared helpers for event-vs-earthquake-vs-flare correlation tests.

Each topic script (wars.py, famines.py, israel.py) imports these.

Tests:
  - yearly_corr(): Pearson + Spearman on yearly counts, raw and regime-detrended
  - lag_corr():    lag scan -10..+10 years on detrended residuals
  - window_test(): for each event year, does the year fall in a high-quake or
                   high-flare year window? Compared to chance via binomial.
  - event_day_window(): for date-precise events (Israel modern dates), does
                        the day fall near an M>=7 quake or X1+ flare?
"""
from __future__ import annotations
import sqlite3
import json
from pathlib import Path
import warnings
from contextlib import closing

from catalog_coverage import apply_coverage

import numpy as np
import pandas as pd
from scipy import stats

from detection_regimes import REGIMES, piecewise_detrend




# ---------- Data loaders ----------

# Shared loaders deliberately distinguish selected catalogue totals, measured
# observations, allocation assumptions, and exact versus imprecise dates.

def _finish(series, source, key, *, include_incomplete=False, coverage=None,
            log10_transform=False, name=None, **attrs):
    out = apply_coverage(series, source, key, include_incomplete=include_incomplete,
                         coverage=coverage)
    if log10_transform:
        out = np.log10(out + 1.0)
    if name is not None:
        log_name = {'war_deaths_active': 'war_deaths', 'famine_deaths_active': 'famine_deaths',
                    'flood_deaths_active': 'flood_deaths'}.get(name, name)
        out.name = 'log10_' + log_name if log10_transform else name
    out.attrs.update(attrs)
    return out


def _count(df, column, lo, hi):
    years = pd.to_numeric(df[column], errors='coerce').dropna().astype(int)
    return years.value_counts().reindex(range(lo, hi + 1), fill_value=0).astype(float)


def _sum(df, year, value, lo, hi):
    """Unknown event magnitudes make the year's total unknown, not zero."""
    values = pd.to_numeric(df[value], errors='coerce')
    years = pd.to_numeric(df[year], errors='coerce')
    grouped = values.groupby(years)
    total = grouped.sum(min_count=1)
    total.loc[grouped.count() < grouped.size()] = np.nan
    return total.reindex(range(lo, hi + 1), fill_value=0).astype(float)


def _allocate(df, value, lo, hi):
    """Allocate across ORIGINAL inclusive lifetime, then slice requested window.

    This is equal annual allocation of event-level totals, not observed annual
    deaths or newly displaced people. Missing totals mark all active years NaN.
    """
    out = pd.Series(0.0, index=range(lo, hi + 1))
    unknown = set()
    for _, row in df.iterrows():
        start = pd.to_numeric(row['start_year'], errors='coerce')
        end = pd.to_numeric(row.get('end_year', start), errors='coerce')
        if pd.isna(start):
            continue
        start = int(start)
        end = start if pd.isna(end) else int(end)
        if end < start:
            raise ValueError(f'Event end {end} precedes start {start}')
        years = range(max(lo, start), min(hi, end) + 1)
        amount = pd.to_numeric(row[value], errors='coerce')
        if pd.isna(amount):
            unknown.update(years)
        elif years:
            out.loc[list(years)] += float(amount) / (end - start + 1)
    if unknown:
        out.loc[sorted(unknown)] = np.nan
    return out


def _allocated_loader(path, key, value, lo, hi, name, log10_transform,
                      include_incomplete, coverage, **attrs):
    out = _allocate(pd.read_csv(path), value, lo, hi)
    return _finish(out, path, key, include_incomplete=include_incomplete,
                   coverage=coverage, log10_transform=log10_transform, name=name,
                   allocation_method='equal_original_active_years', **attrs)


def _load_quakes(path, mag_min, lo, hi, include_incomplete, coverage):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as con:
        df = pd.read_sql('SELECT time_ms FROM quakes WHERE mag >= ?', con,
                         params=(mag_min,))
    df['year'] = pd.to_datetime(df['time_ms'], unit='ms', utc=True).dt.year
    return _finish(_count(df, 'year', lo, hi), path, 'usgs_quakes',
                   include_incomplete=include_incomplete, coverage=coverage,
                   name=f'm{mag_min}_count', unit='events')


def load_yearly_quakes_m7(eq_db_1900: str, year_lo=1900, year_hi=2025, *,
                          include_incomplete=False, coverage=None) -> pd.Series:
    return _load_quakes(eq_db_1900, 7, year_lo, year_hi, include_incomplete, coverage)


def load_yearly_quakes_m8(eq_db_1900: str, year_lo=1900, year_hi=2025, *,
                          include_incomplete=False, coverage=None) -> pd.Series:
    return _load_quakes(eq_db_1900, 8, year_lo, year_hi, include_incomplete, coverage)


def load_yearly_flares_x1(flares_csv: str, year_lo=1976, year_hi=2025, *,
                          include_incomplete=False, coverage=None) -> pd.Series:
    df = pd.read_csv(flares_csv)
    df['year'] = pd.to_datetime(df['date'], errors='coerce', format='mixed').dt.year
    # Legacy input is X-class-only; enforce the advertised threshold if classes
    # are present so a broader refresh cannot silently count M-class flares.
    if 'class' in df:
        strength = pd.to_numeric(df['class'].astype(str).str.extract(r'^X([\d.]+)')[0], errors='coerce')
        df = df[strength >= 1]
    return _finish(_count(df, 'year', year_lo, year_hi), flares_csv, 'flares_xclass.csv',
                   include_incomplete=include_incomplete, coverage=coverage, name='xflare_count')


def load_yearly_wars(wars_csv: str, year_lo=1400, year_hi=2025,
                     include_ongoing: bool = True, *, include_incomplete=False,
                     coverage=None) -> pd.Series:
    df = pd.read_csv(wars_csv)
    if not include_ongoing:
        df = df[pd.to_numeric(df['end_year'], errors='coerce') < year_hi]
    return _finish(_count(df, 'start_year', year_lo, year_hi), wars_csv, 'wars.csv',
                   include_incomplete=include_incomplete, coverage=coverage, name='war_starts')


def load_yearly_wars_split(wars_csv: str, war_type: str, year_lo=1400, year_hi=2025,
                          *, include_incomplete=False, coverage=None) -> pd.Series:
    """War-type analytical categories; no direct equivalence to biblical Greek."""
    df = pd.read_csv(wars_csv)
    df = df[df['war_type'] == war_type]
    return _finish(_count(df, 'start_year', year_lo, year_hi), wars_csv, 'wars.csv',
                   include_incomplete=include_incomplete, coverage=coverage, name=f'war_starts_{war_type}')


def load_yearly_noaa_quakes(noaa_csv: str, year_lo=-2150, year_hi=2025,
                           mag_min: float = 7.0, *, include_incomplete=False,
                           coverage=None) -> pd.Series:
    """Recorded significant quakes; sparse historical coverage is selection-biased."""
    df = pd.read_csv(noaa_csv)
    df = df[pd.to_numeric(df['eqMagnitude'], errors='coerce') >= mag_min]
    return _finish(_count(df, 'year', year_lo, year_hi), noaa_csv, 'noaa_significant_earthquakes.csv',
                   include_incomplete=include_incomplete, coverage=coverage, name=f'noaa_quakes_mag_ge_{mag_min}')


def load_yearly_noaa_volcanic_events(noaa_csv: str, year_lo=-4360, year_hi=2025,
                                    deaths_min: float = 0, *, include_incomplete=False,
                                    coverage=None) -> pd.Series:
    df = pd.read_csv(noaa_csv)
    if deaths_min > 0:
        df = df[pd.to_numeric(df['deathsTotal'], errors='coerce') >= deaths_min]
    return _finish(_count(df, 'year', year_lo, year_hi), noaa_csv, 'noaa_volcanic_events.csv',
                   include_incomplete=include_incomplete, coverage=coverage, name=f'noaa_volcanoes_deaths_ge_{int(deaths_min)}')


def load_yearly_cow_wars(cow_csv: str, year_lo=1816, year_hi=2007,
                        war_type: str = 'interstate', *, include_incomplete=False,
                        coverage=None) -> pd.Series:
    df = pd.read_csv(cow_csv, encoding='latin-1').drop_duplicates('WarNum')
    return _finish(_count(df, 'StartYear1', year_lo, year_hi), cow_csv, f'cow_{war_type}_wars_v4.csv',
                   include_incomplete=include_incomplete, coverage=coverage, name=f'cow_{war_type}_wars')


def load_yearly_ucdp_conflicts(ucdp_csv: str, year_lo=1946, year_hi=2025,
                              conflict_types: list = None, intensity_min: int = 1,
                              *, include_incomplete=False, coverage=None) -> pd.Series:
    """Active conflict-years (not onsets), unique by conflict_id and year."""
    df = pd.read_csv(ucdp_csv).drop_duplicates(['conflict_id', 'year'])
    df = df[df['intensity_level'] >= intensity_min]
    if conflict_types:
        df = df[df['type_of_conflict'].isin(conflict_types)]
    return _finish(_count(df, 'year', year_lo, year_hi), ucdp_csv, 'ucdp_prio_conflicts.csv',
                   include_incomplete=include_incomplete, coverage=coverage, name='ucdp_active_conflicts')


def load_yearly_war_deaths_ucdp(ucdp_csv: str, year_lo=1946, year_hi=2025,
                               log10_transform: bool = False, minor_floor: float = 25.0,
                               war_floor: float = 1000.0, *, include_incomplete=False,
                               coverage=None) -> pd.Series:
    """Intensity-band lower-bound proxy, NOT measured battle deaths."""
    df = pd.read_csv(ucdp_csv).drop_duplicates(['conflict_id', 'year'])
    df['floor'] = df['intensity_level'].map({1: minor_floor, 2: war_floor})
    return _finish(_sum(df, 'year', 'floor', year_lo, year_hi), ucdp_csv, 'ucdp_prio_conflicts.csv',
                   include_incomplete=include_incomplete, coverage=coverage, log10_transform=log10_transform,
                   name='ucdp_war_deaths_floor', metric_kind='intensity_band_lower_bound_proxy')


def load_yearly_war_deaths_split(wars_csv: str, war_type: str, year_lo=1400, year_hi=2025,
                                log10_transform: bool = False, *, include_incomplete=False,
                                coverage=None) -> pd.Series:
    df = pd.read_csv(wars_csv)
    return _finish(_allocate(df[df['war_type'] == war_type], 'deaths_estimate', year_lo, year_hi),
                   wars_csv, 'wars.csv', include_incomplete=include_incomplete, coverage=coverage,
                   log10_transform=log10_transform, name=f'war_deaths_{war_type}',
                   allocation_method='equal_original_active_years')


def load_yearly_war_deaths_active(wars_csv: str, year_lo=1400, year_hi=2025,
                                 log10_transform: bool = False, *, include_incomplete=False,
                                 coverage=None) -> pd.Series:
    return _allocated_loader(wars_csv, 'wars.csv', 'deaths_estimate', year_lo, year_hi,
                             'war_deaths_active', log10_transform, include_incomplete, coverage)


def load_yearly_famines(famines_csv: str, year_lo=1500, year_hi=2025, *,
                        include_incomplete=False, coverage=None) -> pd.Series:
    return _finish(_count(pd.read_csv(famines_csv), 'start_year', year_lo, year_hi),
                   famines_csv, 'famines.csv', include_incomplete=include_incomplete,
                   coverage=coverage, name='famine_starts')


def load_yearly_famine_deaths_active(famines_csv: str, year_lo=1500, year_hi=2025,
                                    log10_transform: bool = False, *, include_incomplete=False,
                                    coverage=None) -> pd.Series:
    return _allocated_loader(famines_csv, 'famines.csv', 'deaths_estimate', year_lo, year_hi,
                             'famine_deaths_active', log10_transform, include_incomplete, coverage)


def load_yearly_famine_deaths_wpf(deaths_by_year_csv: str, year_lo=1870, year_hi=2025,
                                 log10_transform: bool = False, *, include_incomplete=False,
                                 coverage=None) -> pd.Series:
    df = pd.read_csv(deaths_by_year_csv)
    df = df[~df['entity'].str.startswith('World', na=False)]
    return _finish(_sum(df, 'year', 'famine_deaths', year_lo, year_hi), deaths_by_year_csv,
                   'famine_deaths_by_year.csv', include_incomplete=include_incomplete,
                   coverage=coverage, log10_transform=log10_transform, name='wpf_famine_deaths')


# ---------- Canonical flood events ----------

def load_canonical_flood_events(floods_csv: str, dedupe_match_groups: bool = True) -> pd.DataFrame:
    """One source-priority reconciliation BEFORE any threshold or date filter.

    EM-DAT is preferred to DFO, matching the feeder's priority. Ties are stable
    by source ID/date, never mortality. Preserve match-group row counts and toll
    disagreement for audit. Existing match groups are provisional links, not a
    claim that multinational/group collisions have been manually adjudicated.
    """
    df = pd.read_csv(floods_csv, low_memory=False)
    df['deaths'] = pd.to_numeric(df['deaths'], errors='coerce')
    df['start'] = pd.to_datetime(df['start_date'], errors='coerce', format='mixed')
    df['end'] = pd.to_datetime(df['end_date'], errors='coerce', format='mixed').fillna(df['start'])
    df['year'] = df['start'].dt.year
    df['invalid_interval'] = df['end'] < df['start']
    df['date_precision'] = df.get('date_precision', pd.Series('day', index=df.index))
    exact = df['start_date'].astype(str).str.match(r'^\d{4}-\d{2}-\d{2}(?:$|[T ])')
    df.loc[~exact, 'date_precision'] = 'imprecise'
    df['_row'] = np.arange(len(df))
    df['_priority'] = df.get('source', pd.Series('', index=df.index)).map({'EM-DAT': 0, 'DFO': 1}).fillna(2)
    df['_source_id'] = df.get('source_id', pd.Series('', index=df.index)).fillna('').astype(str)
    df['canonical_event_id'] = 'row:' + df['_row'].astype(str)
    if dedupe_match_groups and 'match_group_id' in df:
        grouped = df['match_group_id'].notna()
        df.loc[grouped, 'canonical_event_id'] = 'match:' + df.loc[grouped, 'match_group_id'].astype(str)
        # Unmatched records with a stable source ID can still be exact duplicates.
        identified = ~grouped & df['_source_id'].ne('')
        source = df.get('source', pd.Series('', index=df.index)).fillna('').astype(str)
        df.loc[identified, 'canonical_event_id'] = source[identified] + ':' + df.loc[identified, '_source_id']
        groups = df.groupby('canonical_event_id', sort=False)
        df['source_row_count'] = groups['deaths'].transform('size')
        df['deaths_min_reported'] = groups['deaths'].transform('min')
        df['deaths_max_reported'] = groups['deaths'].transform('max')
        df['distinct_source_ids'] = groups['_source_id'].transform('nunique')
        if 'cause' in df:
            df['linked_causes'] = groups['cause'].transform(lambda x: '; '.join(sorted(set(x.dropna().astype(str)))))
        df = df.sort_values(['_priority', '_source_id', 'start', '_row'], kind='stable').drop_duplicates('canonical_event_id')
    else:
        df['source_row_count'] = 1
        df['deaths_min_reported'] = df['deaths']
        df['deaths_max_reported'] = df['deaths']
        df['distinct_source_ids'] = 1
    df = df.sort_values(['start', '_source_id', '_row'], kind='stable').drop(columns=['_priority', '_source_id', '_row']).reset_index(drop=True)
    df.attrs['deduplication'] = 'EM-DAT before DFO; stable source ID tie; before filters'
    df.attrs['linkage_status'] = 'existing match groups; ambiguities require source adjudication'
    return df


def load_yearly_flood_events(floods_csv: str, year_lo=1900, year_hi=2025,
                             deaths_min: float = 0, dedupe_match_groups: bool = True,
                             *, include_incomplete=False, coverage=None) -> pd.Series:
    df = load_canonical_flood_events(floods_csv, dedupe_match_groups)
    if deaths_min > 0:
        df = df[df['deaths'] >= deaths_min]
    return _finish(_count(df, 'year', year_lo, year_hi), floods_csv, 'floods.csv',
                   include_incomplete=include_incomplete, coverage=coverage,
                   name=f'flood_events_deaths_ge_{int(deaths_min)}')


def load_yearly_flood_deaths(floods_csv: str, year_lo=1900, year_hi=2025,
                             log10_transform: bool = False, dedupe_match_groups: bool = True,
                             *, include_incomplete=False, coverage=None) -> pd.Series:
    """Event totals allocated by actual calendar days in ORIGINAL full interval."""
    df = load_canonical_flood_events(floods_csv, dedupe_match_groups)
    out = pd.Series(0.0, index=range(year_lo, year_hi + 1))
    unknown = set()
    for _, row in df.dropna(subset=['start']).iterrows():
        start, end = row['start'].normalize(), row['end'].normalize()
        if end < start:
            # Invalid source interval: do not silently swap dates or invent a day.
            unknown.update(range(max(year_lo, end.year), min(year_hi, start.year) + 1))
            continue
        for year in range(max(year_lo, start.year), min(year_hi, end.year) + 1):
            if pd.isna(row['deaths']):
                unknown.add(year)
            else:
                days = (min(end, pd.Timestamp(year, 12, 31)) - max(start, pd.Timestamp(year, 1, 1))).days + 1
                out.loc[year] += float(row['deaths']) * days / ((end - start).days + 1)
    if unknown:
        out.loc[sorted(unknown)] = np.nan
    return _finish(out, floods_csv, 'floods.csv', include_incomplete=include_incomplete,
                   coverage=coverage, log10_transform=log10_transform, name='flood_deaths_active',
                   allocation_method='equal_original_active_days')


def load_flood_event_dates(floods_csv: str, deaths_min: float = 1000,
                           exclude_tsunami: bool = True):
    df = load_canonical_flood_events(floods_csv)
    if deaths_min > 0:
        df = df[df['deaths'] >= deaths_min]
    if exclude_tsunami and 'cause' in df:
        df = df[~df.get('linked_causes', df['cause']).astype(str).str.contains('tsunami|tidal', case=False, na=False)]
    exact = df['date_precision'].astype(str).str.lower().isin(['day', 'exact', 'daily'])
    return df.loc[exact, 'start'].dropna().dt.normalize().tolist()


# ---------- Pandemic, volcano, cyclone, astronomical catalogues ----------

def load_yearly_pandemic_deaths(pandemics_csv: str, year_lo=1500, year_hi=2025,
                                log10_transform: bool = False, *, include_incomplete=False,
                                coverage=None) -> pd.Series:
    return _allocated_loader(pandemics_csv, 'pandemics.csv', 'deaths_estimate', year_lo, year_hi,
                             'pandemic_deaths', log10_transform, include_incomplete, coverage)


def load_yearly_pandemic_starts(pandemics_csv: str, year_lo=1500, year_hi=2025,
                                *, include_incomplete=False, coverage=None) -> pd.Series:
    return _finish(_count(pd.read_csv(pandemics_csv), 'start_year', year_lo, year_hi),
                   pandemics_csv, 'pandemics.csv', include_incomplete=include_incomplete,
                   coverage=coverage, name='pandemic_starts')


def _volcanoes(path, vei_min):
    df = pd.read_csv(path)
    vei = pd.to_numeric(df['vei'].astype(str).str.extract(r'(\d+)')[0], errors='coerce')
    return df[vei >= vei_min].copy()


def load_yearly_volcanoes(volcanoes_csv: str, year_lo=1500, year_hi=2025,
                          vei_min: int = 5, *, include_incomplete=False, coverage=None) -> pd.Series:
    return _finish(_count(_volcanoes(volcanoes_csv, vei_min), 'year', year_lo, year_hi),
                   volcanoes_csv, 'volcanoes.csv', include_incomplete=include_incomplete,
                   coverage=coverage, name=f'volcanoes_vei_ge_{vei_min}')


def _exact_dates(df):
    """Month/year-only records do not have a defensible daily event window."""
    if 'date' in df:
        raw = df['date'].astype(str)
        exact = raw.str.match(r'^\d{4}-\d{2}-\d{2}(?:$|[T ])')
        dates = pd.to_datetime(raw.where(exact), errors='coerce', format='mixed')
    elif all(k in df for k in ('year', 'month', 'day')):
        dates = pd.to_datetime(df[['year', 'month', 'day']].apply(pd.to_numeric, errors='coerce'), errors='coerce')
    else:
        return []
    if 'date_precision' in df:
        dates = dates.where(df['date_precision'].astype(str).str.lower().isin(['day', 'exact', 'daily']))
    return dates.dropna().dt.normalize().tolist()


def load_volcano_dates(volcanoes_csv: str, vei_min: int = 5):
    return _exact_dates(_volcanoes(volcanoes_csv, vei_min))


def load_yearly_cyclones(cyclones_csv: str, year_lo=1700, year_hi=2025,
                         deaths_min: float = 1000, *, include_incomplete=False,
                         coverage=None) -> pd.Series:
    df = pd.read_csv(cyclones_csv)
    if deaths_min > 0:
        df = df[pd.to_numeric(df['deaths_estimate'], errors='coerce') >= deaths_min]
    return _finish(_count(df, 'year', year_lo, year_hi), cyclones_csv, 'cyclones.csv',
                   include_incomplete=include_incomplete, coverage=coverage,
                   name=f'cyclones_deaths_ge_{int(deaths_min)}')


def load_yearly_cyclone_deaths(cyclones_csv: str, year_lo=1700, year_hi=2025,
                               log10_transform: bool = False, *, include_incomplete=False,
                               coverage=None) -> pd.Series:
    return _finish(_sum(pd.read_csv(cyclones_csv), 'year', 'deaths_estimate', year_lo, year_hi),
                   cyclones_csv, 'cyclones.csv', include_incomplete=include_incomplete,
                   coverage=coverage, log10_transform=log10_transform, name='cyclone_deaths')


def load_cyclone_dates(cyclones_csv: str, deaths_min: float = 1000):
    df = pd.read_csv(cyclones_csv)
    if deaths_min > 0:
        df = df[pd.to_numeric(df['deaths_estimate'], errors='coerce') >= deaths_min]
    return _exact_dates(df)


def load_astronomical_signs(astro_csv: str, year_lo=1500, year_hi=2025, types: list = None):
    """Selected examples; this is NOT a complete eclipse denominator."""
    df = pd.read_csv(astro_csv)
    df['year'] = pd.to_numeric(df['date'].astype(str).str.extract(r'^(-?\d{1,4})-')[0], errors='coerce')
    df['date'] = pd.to_datetime(df['date'], errors='coerce', format='mixed')
    df = df[df['year'].between(year_lo, year_hi)]
    if types:
        df = df[df['type'].isin(types)]
    return df


def load_yearly_astro_events(astro_csv: str, year_lo=1500, year_hi=2025,
                             types: list = None, *, include_incomplete=False, coverage=None) -> pd.Series:
    df = load_astronomical_signs(astro_csv, year_lo, year_hi, types)
    return _finish(_count(df, 'year', year_lo, year_hi), astro_csv, 'astronomical_signs.csv',
                   include_incomplete=include_incomplete, coverage=coverage, name='astro_events')


# ---------- Human outcomes remain distinct from physical hazard intensity ----------

def load_yearly_droughts(droughts_csv: str, year_lo=1850, year_hi=2025,
                         intensity_min: float = 0, *, intensity_metric='people_affected',
                         include_incomplete=False, coverage=None) -> pd.Series:
    """Listed active drought-years. Optional threshold uses ONE named metric.

    Legacy intensity_min now thresholds people_affected only, never max(deaths,
    affected). Without a threshold, retain events lacking human-impact estimates.
    This selected catalogue does not contain measured physical drought severity.
    """
    if intensity_metric not in ('people_affected', 'deaths_estimate'):
        raise ValueError('Use people_affected or deaths_estimate; physical drought severity is unavailable')
    df = pd.read_csv(droughts_csv)
    if intensity_min > 0:
        df = df[pd.to_numeric(df[intensity_metric], errors='coerce') >= intensity_min]
    df['count'] = pd.to_numeric(df['end_year'], errors='coerce').fillna(df['start_year']) - df['start_year'] + 1
    return _finish(_allocate(df, 'count', year_lo, year_hi), droughts_csv, 'droughts.csv',
                   include_incomplete=include_incomplete, coverage=coverage,
                   name=f'drought_active_{intensity_metric}_ge_{int(intensity_min)}',
                   metric_kind='listed_active_events', threshold_metric=intensity_metric)


def load_yearly_drought_affected(droughts_csv: str, year_lo=1850, year_hi=2025,
                                log10_transform: bool = False, *, include_incomplete=False,
                                coverage=None) -> pd.Series:
    """Affected-population allocation proxy, not measured annual flow or severity."""
    return _allocated_loader(droughts_csv, 'droughts.csv', 'people_affected', year_lo, year_hi,
                             'drought_affected_allocation_proxy', log10_transform,
                             include_incomplete, coverage, metric_kind='human_impact_allocation_proxy',
                             unit='allocated_event_total_people_per_year')


def load_yearly_drought_deaths(droughts_csv: str, year_lo=1850, year_hi=2025,
                              log10_transform: bool = False, *, include_incomplete=False,
                              coverage=None) -> pd.Series:
    """Deaths from listed drought events; may overlap famine events."""
    return _allocated_loader(droughts_csv, 'droughts.csv', 'deaths_estimate', year_lo, year_hi,
                             'drought_deaths_allocation_proxy', log10_transform,
                             include_incomplete, coverage, metric_kind='mortality_allocation_proxy',
                             unit='allocated_deaths_per_year', overlap_warning='May duplicate famine outcomes')


def load_yearly_drought_intensity(droughts_csv: str, year_lo=1850, year_hi=2025,
                                 log10_transform: bool = False, *, include_incomplete=False,
                                 coverage=None) -> pd.Series:
    """Compatibility alias for affected population ONLY; no physical severity data."""
    warnings.warn('load_yearly_drought_intensity now returns affected-population allocation proxy; '
                  'use load_yearly_drought_affected or load_yearly_drought_deaths explicitly',
                  FutureWarning, stacklevel=2)
    return load_yearly_drought_affected(droughts_csv, year_lo, year_hi, log10_transform,
                                       include_incomplete=include_incomplete, coverage=coverage)


def load_yearly_refugee_displaced(refugees_csv: str, year_lo=1947, year_hi=2025,
                                 log10_transform: bool = False, *, include_incomplete=False,
                                 coverage=None) -> pd.Series:
    """Allocated crisis-total proxy; not annual new displacement or population stock."""
    return _allocated_loader(refugees_csv, 'refugees.csv', 'displaced_estimate', year_lo, year_hi,
                             'refugee_displaced', log10_transform, include_incomplete, coverage,
                             metric_kind='crisis_total_allocation_proxy')


def load_yearly_economic_crises(crises_csv: str, year_lo=1800, year_hi=2025,
                               severity_min: str = None, *, include_incomplete=False,
                               coverage=None) -> pd.Series:
    df = pd.read_csv(crises_csv)
    if severity_min:
        order = {'medium': 0, 'severe': 1, 'extreme': 2}
        df = df[df['severity'].map(order) >= order[severity_min]]
    return _finish(_count(df, 'year', year_lo, year_hi), crises_csv, 'economic_crises.csv',
                   include_incomplete=include_incomplete, coverage=coverage, name=f'economic_crises_{severity_min or "all"}')


def load_yearly_coups(coups_csv: str, year_lo=1950, year_hi=2025, outcome: str = None,
                     *, include_incomplete=False, coverage=None) -> pd.Series:
    df = pd.read_csv(coups_csv)
    if outcome:
        df = df[df['outcome'] == outcome]
    return _finish(_count(df, 'year', year_lo, year_hi), coups_csv, 'coups.csv',
                   include_incomplete=include_incomplete, coverage=coverage, name=f'coups_{outcome or "all"}')


def load_yearly_heat_wave_deaths(heat_csv: str, year_lo=1880, year_hi=2025,
                               log10_transform: bool = False, *, include_incomplete=False,
                               coverage=None) -> pd.Series:
    return _allocated_loader(heat_csv, 'heat_waves.csv', 'deaths_estimate', year_lo, year_hi,
                             'heat_wave_deaths', log10_transform, include_incomplete, coverage)


def load_yearly_heat_wave_events(heat_csv: str, year_lo=1880, year_hi=2025,
                               deaths_min: float = 0, *, include_incomplete=False,
                               coverage=None) -> pd.Series:
    df = pd.read_csv(heat_csv)
    if deaths_min > 0:
        df = df[pd.to_numeric(df['deaths_estimate'], errors='coerce') >= deaths_min]
    return _finish(_count(df, 'start_year', year_lo, year_hi), heat_csv, 'heat_waves.csv',
                   include_incomplete=include_incomplete, coverage=coverage, name=f'heat_wave_events_deaths_ge_{int(deaths_min)}')


def load_yearly_stock_crashes(crashes_csv: str, year_lo=1900, year_hi=2025,
                             drawdown_min: float = 0.0, *, include_incomplete=False,
                             coverage=None) -> pd.Series:
    df = pd.read_csv(crashes_csv)
    if drawdown_min > 0:
        df = df[pd.to_numeric(df['pct_drawdown'], errors='coerce') >= drawdown_min]
    return _finish(_count(df, 'year', year_lo, year_hi), crashes_csv, 'stock_crashes.csv',
                   include_incomplete=include_incomplete, coverage=coverage, name=f'stock_crashes_dd_ge_{int(drawdown_min)}')


def load_yearly_stock_drawdown_intensity(crashes_csv: str, year_lo=1900, year_hi=2025,
                                       log10_transform: bool = False, *, include_incomplete=False,
                                       coverage=None) -> pd.Series:
    return _finish(_sum(pd.read_csv(crashes_csv), 'year', 'pct_drawdown', year_lo, year_hi),
                   crashes_csv, 'stock_crashes.csv', include_incomplete=include_incomplete,
                   coverage=coverage, log10_transform=log10_transform, name='stock_drawdown_pct',
                   metric_kind='sum_of_event_drawdowns_not_market_return')


def _terror(path, value, lo, hi, log10_transform, include_incomplete, coverage):
    df = pd.read_csv(path)
    values = pd.to_numeric(df[value], errors='coerce')
    # Annual observations: absent rows are missing, even within coverage.
    out = pd.Series(values.to_numpy(), index=pd.to_numeric(df['year'])).reindex(range(lo, hi + 1))
    return _finish(out, path, 'terrorism.csv', include_incomplete=include_incomplete,
                   coverage=coverage, log10_transform=log10_transform, name=f'terrorism_{value}')


def load_yearly_terrorism_events(terror_csv: str, year_lo=1970, year_hi=2025, *,
                                include_incomplete=False, coverage=None) -> pd.Series:
    return _terror(terror_csv, 'events', year_lo, year_hi, False, include_incomplete, coverage)


def load_yearly_terrorism_deaths(terror_csv: str, year_lo=1970, year_hi=2025,
                               log10_transform: bool = False, *, include_incomplete=False,
                               coverage=None) -> pd.Series:
    return _terror(terror_csv, 'deaths', year_lo, year_hi, log10_transform, include_incomplete, coverage)


def load_yearly_coup_deaths(coups_csv: str, year_lo=1950, year_hi=2025,
                           log10_transform: bool = False, *, include_incomplete=False,
                           coverage=None) -> pd.Series:
    return _finish(_sum(pd.read_csv(coups_csv), 'year', 'deaths_estimate', year_lo, year_hi),
                   coups_csv, 'coups.csv', include_incomplete=include_incomplete,
                   coverage=coverage, log10_transform=log10_transform, name='coup_deaths')


def load_levant_quakes(eq_db_modern: str, lat=31.78, lon=35.21, radius_km=500,
                        mag_min=4.0):
    """Load modern Levant quakes from USGS M>=4 1965+ catalog (spatial filter)."""
    with closing(sqlite3.connect(Path(eq_db_modern).resolve().as_uri() + '?mode=ro', uri=True)) as con:
        q = pd.read_sql('SELECT time_ms, mag, lat, lon FROM quakes WHERE mag>=?', con, params=(mag_min,))
    # Approximate flat-earth distance — fine at this scale
    dlat = q["lat"] - lat
    dlon = (q["lon"] - lon) * np.cos(np.deg2rad(lat))
    dist_km = np.sqrt(dlat**2 + dlon**2) * 111.0
    q = q[dist_km <= radius_km].copy()
    q["date"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.tz_localize(None)
    return q


def load_modern_quakes_dates(eq_db_modern: str, mag_min=7.0):
    with closing(sqlite3.connect(Path(eq_db_modern).resolve().as_uri() + '?mode=ro', uri=True)) as con:
        q = pd.read_sql('SELECT time_ms, mag FROM quakes WHERE mag>=?', con, params=(mag_min,))
    q["date"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.tz_localize(None)
    return q


def load_flare_dates(flares_csv: str):
    return pd.read_csv(flares_csv, parse_dates=["date"])


def load_israel_dates(israel_json: str):
    with open(israel_json) as f:
        return json.load(f)


# ---------- Core tests ----------

def yearly_corr(a: pd.Series, b: pd.Series, regime_key_a: str = None,
                regime_key_b: str = None) -> dict:
    """
    Pearson + Spearman on overlap years. Returns raw + per-regime-detrended.
    Detrending uses REGIMES[regime_key] for each series.
    """
    overlap = a.index.intersection(b.index)
    a2 = a.loc[overlap].astype(float)
    b2 = b.loc[overlap].astype(float)
    mask = np.isfinite(a2) & np.isfinite(b2)
    a2 = a2[mask]; b2 = b2[mask]

    out = {"n": int(mask.sum()), **{key: float("nan") for key in
           ("raw_r", "raw_p", "raw_rho", "raw_p_spear", "det_r", "det_p")}}
    if len(a2) < 3 or a2.std() == 0 or b2.std() == 0:
        return out
    r, p = stats.pearsonr(a2, b2)
    rs, ps = stats.spearmanr(a2, b2)
    out |= {"raw_r": r, "raw_p": p, "raw_rho": rs, "raw_p_spear": ps}

    if regime_key_a and regime_key_b:
        ad = piecewise_detrend(a2, REGIMES.get(regime_key_a, []))
        bd = piecewise_detrend(b2, REGIMES.get(regime_key_b, []))
        m2 = ~(ad.isna() | bd.isna())
        if m2.sum() >= 3 and ad[m2].std() > 1e-12 and bd[m2].std() > 1e-12:
            r2, p2 = stats.pearsonr(ad[m2], bd[m2])
            out |= {"det_r": r2, "det_p": p2}
        else:
            out |= {"det_r": float("nan"), "det_p": float("nan")}
    return out


def lag_corr(a: pd.Series, b: pd.Series, lags: range,
             regime_key_a: str = None, regime_key_b: str = None) -> pd.DataFrame:
    """Lag-correlation on regime-detrended residuals.
    Positive lag = b leads a by lag years (i.e. correlate a with b shifted forward)."""
    overlap = a.index.intersection(b.index)
    a2 = a.loc[overlap].astype(float)
    b2 = b.loc[overlap].astype(float)
    if regime_key_a:
        a2 = piecewise_detrend(a2, REGIMES.get(regime_key_a, []))
    if regime_key_b:
        b2 = piecewise_detrend(b2, REGIMES.get(regime_key_b, []))

    rows = []
    for lag in lags:
        bs = b2.shift(lag)
        mask = ~(a2.isna() | bs.isna())
        if mask.sum() < 5:
            rows.append({"lag": lag, "r": float("nan"), "p": float("nan"),
                         "n": int(mask.sum())})
            continue
        r, p = stats.pearsonr(a2[mask], bs[mask])
        rows.append({"lag": lag, "r": r, "p": p, "n": int(mask.sum())})
    return pd.DataFrame(rows)


def event_window_test(event_dates: list, target_dates: list,
                      window_days: int, all_dates: set) -> dict:
    """
    For a set of point events, count how many fall within +/- window_days
    of any target date. Compare to chance via binomial.

    `all_dates` is the population of valid days (e.g. all days in the modern
    quake catalog window). `target_dates` is the set of target events
    (e.g. M>=7 quakes or X1+ flares).
    """
    target_set = set(pd.to_datetime(target_dates).normalize())
    # build the "near a target" window
    near = set()
    for d in target_set:
        for k in range(-window_days, window_days + 1):
            near.add(d + pd.Timedelta(days=k))
    near &= all_dates
    n_total = len(all_dates)
    n_near = len(near)
    events = [pd.Timestamp(d).normalize() for d in event_dates if pd.Timestamp(d).normalize() in all_dates]
    n_events = len(events)
    if n_events == 0 or n_total == 0:
        return {"n_events": n_events, "n_near": n_near, "n_total": n_total,
                "observed_in_window": 0, "expected": 0,
                "ratio": float("nan"), "p_two_sided": float("nan")}
    observed = sum(1 for d in events if d in near)
    expected = n_events * n_near / n_total
    p = stats.binomtest(observed, n=n_events, p=n_near / n_total,
                        alternative="two-sided").pvalue
    return {
        "n_events": n_events, "n_target": len(target_set),
        "n_near": n_near, "n_total": n_total,
        "window_days": window_days,
        "observed_in_window": observed,
        "expected": expected,
        "ratio": observed / expected if expected else float("nan"),
        "p_two_sided": p,
    }
