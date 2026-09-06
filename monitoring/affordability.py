"""Descriptive purchasing power from exact WFP market/staple/daily-wage pairs.

Rules were fixed in extension_plan.json before extension results were examined.
These revised historical snapshots are not release-time backtests. No CPI,
representative national wages, seasonal adjustment or missing-value imputation.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from monitoring.feeds import is_food_commodity, kg_unit

PLAN = {
    'baseline_years': [2015, 2019],
    'minimum_baseline_months': 36,
    'minimum_months_each_baseline_year': 6,
    'minimum_markets': 1,
    'minimum_staples_per_market': 1,
    'required_fixed_basket_coverage': 1.0,
}
PLAN_PATH = Path(__file__).with_name('extension_plan.json')
COUNTRIES = ['ISR', 'PSE', 'LBN', 'UKR', 'SDN', 'ETH', 'SOM', 'YEM']
IDENTITY = ['country', 'market_id', 'commodity_id', 'commodity', 'currency', 'unit',
            'food_unit_original', 'food_unit_kg', 'food_normalized_unit', 'food_price_type',
            'wage_series_signature']
MONTHLY_COLUMNS = IDENTITY + ['series_id', 'month', 'value', 'numerator', 'denominator',
    'period_start', 'period_end', 'source_url', 'source_version', 'published_at', 'fetched_at',
    'dimensions', 'duplicate_observation_count', 'mom_pct', 'mom_status', 'yoy_pct', 'yoy_status',
    'index_2015_2019', 'baseline_geometric_mean', 'basket_member']
MEMBER_COLUMNS = IDENTITY + ['series_id', 'baseline_months', 'baseline_year_counts',
    'baseline_geometric_mean', 'eligible', 'eligibility_reason', 'weight']
BASKET_COLUMNS = ['country', 'month', 'expected_members', 'observed_members', 'member_coverage',
    'expected_markets', 'complete_markets', 'index', 'status', 'mom_pct', 'mom_status', 'yoy_pct', 'yoy_status']
ANNUAL_COLUMNS = ['country', 'series_id', 'year', 'observed_months', 'value', 'status', 'yoy_pct', 'yoy_status']
DIAGNOSTIC_COLUMNS = ['source_row', 'country', 'month', 'series_id', 'reason']


def _plan(plan):
    committed = json.loads(PLAN_PATH.read_text())['affordability']
    for key, value in PLAN.items():
        if committed.get(key) != value:
            raise ValueError(f'Committed affordability plan differs from implemented frozen rule: {key}')
    supplied = plan or {}
    if 'affordability' in supplied:
        supplied = supplied['affordability']
    result = dict(committed, **supplied)
    # These descriptive methods implement the frozen design, not arbitrary weights.
    for key, value in PLAN.items():
        if result[key] != value:
            raise ValueError(f'Affordability rule differs from frozen design: {key}')
    return result


def _json(value):
    result = json.loads(value) if isinstance(value, str) else value
    if not isinstance(result, dict):
        raise ValueError('dimensions must be an object')
    return result


def _dump(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _hash(value):
    return hashlib.sha256(_dump(value).encode()).hexdigest()


def _positive(value):
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (ValueError, TypeError):
        return False


def _true(value):
    return str(value).strip().lower() in {'true', '1', 'yes'}


def _date(value):
    stamp = pd.to_datetime(value, errors='coerce', utc=True)
    return stamp.tz_convert(None) if pd.notna(stamp) else pd.NaT


def _prepare(observations, cutoff):
    """Quarantine malformed observations and conflicting exact-series month pairs."""
    good, bad = [], []
    if observations.empty or 'metric' not in observations:
        return pd.DataFrame(columns=MONTHLY_COLUMNS), pd.DataFrame(columns=DIAGNOSTIC_COLUMNS)
    selected = observations[observations.metric.eq('staple_kg_per_daily_wage')]
    for ordinal, (_, r) in enumerate(selected.iterrows()):
        entry = {'source_row': ordinal, 'country': str(r.get('country', '')),
                 'month': '', 'series_id': ''}
        reason = None
        try:
            dims = _json(r.get('dimensions'))
            if len(entry['country']) != 3 or not entry['country'].isalpha() or not entry['country'].isupper():
                raise ValueError('missing or invalid ISO3 country')
            start, end = _date(r.get('period_start')), _date(r.get('period_end'))
            if pd.isna(start) or pd.isna(end):
                raise ValueError('invalid period date')
            month = start.to_period('M'); entry['month'] = str(month)
            if start != month.start_time or end != month.end_time.normalize():
                raise ValueError('period is not one full calendar month')
            if month > cutoff:
                raise ValueError('uncompleted or future month')
            if str(r.get('source_id', '')).lower() != 'wfp' or r.get('frequency') != 'monthly':
                raise ValueError('not a monthly WFP observation')
            if str(dims.get('type', 'actual')).lower() not in {'actual', 'current', 'observed'} or _true(r.get('projected', False)):
                raise ValueError('projected observation')
            if any(_true(dims.get(k, False)) or _true(r.get(k, False)) for k in ['partial', 'is_partial']):
                raise ValueError('source marks period partial')
            if r.get('unit') != 'kg/day_wage':
                raise ValueError('incompatible ratio unit')
            if not all(_positive(r.get(k)) for k in ['value', 'numerator', 'denominator']):
                raise ValueError('missing or nonpositive ratio/wage/price')
            value, wage, price = [float(r[k]) for k in ['value', 'numerator', 'denominator']]
            if not math.isclose(value, wage / price, rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError('ratio does not match wage / price per kg')
            required = ['market_id', 'commodity_id', 'commodity', 'currency', 'food_unit_original',
                        'food_normalized_unit', 'food_price_type', 'wage_series_signature']
            if any(k not in dims or dims[k] is None or str(dims[k]).strip().lower() in {'', 'nan', 'none'} for k in required):
                raise ValueError('missing exact pair metadata')
            signature = _json(dims['wage_series_signature'])
            if any(str(signature.get(k, '')).strip().lower() in {'', 'nan', 'none', '<na>'} for k in ['commodity_id', 'commodity', 'pricetype', 'currency']):
                raise ValueError('incomplete wage signature')
            if signature.get('unit') != 'DAY' or signature.get('currency') != dims['currency']:
                raise ValueError('incompatible canonical wage signature')
            if 'wage' not in signature['commodity'].lower() or 'non-qualified' not in signature['commodity'].lower():
                raise ValueError('not a non-qualified daily wage series')
            if dims['food_normalized_unit'] != 'KG' or dims['food_price_type'].lower() != 'retail':
                raise ValueError('not a retail price normalized to kg')
            unitkg = kg_unit(dims['food_unit_original'])
            if not unitkg or not _positive(dims.get('food_unit_kg')) or not math.isclose(unitkg, float(dims['food_unit_kg']), rel_tol=1e-12):
                raise ValueError('food unit conversion mismatch')
            if not is_food_commodity(dims['commodity']) or not any(s in dims['commodity'].lower() for s in ['wheat', 'barley', 'maize', 'rice', 'sorghum']):
                raise ValueError('not a monitored food staple')
            identity = {k: str(dims[k]) for k in required if k != 'wage_series_signature'}
            identity.update(country=entry['country'], unit='kg/day_wage', food_unit_kg=float(unitkg),
                            wage_series_signature=_dump(signature))
            series = _hash(identity); entry['series_id'] = series
            good.append(dict(identity, series_id=series, month=str(month), value=value, numerator=wage,
                denominator=price, period_start=str(start.date()), period_end=str(end.date()),
                source_url=r.get('source_url'), source_version=r.get('source_version'),
                published_at=r.get('published_at'), fetched_at=r.get('fetched_at'), dimensions=_dump(dims),
                _source_row=ordinal))
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            reason = str(exc)
        if reason:
            bad.append(dict(entry, reason=reason))
    if not good:
        return pd.DataFrame(columns=MONTHLY_COLUMNS), pd.DataFrame(bad, columns=DIAGNOSTIC_COLUMNS)
    accepted = []
    for (series, month), group in pd.DataFrame(good).groupby(['series_id', 'month'], sort=True):
        if any(group[k].nunique(dropna=False) > 1 for k in ['value', 'numerator', 'denominator']):
            for _, row in group.iterrows():
                bad.append({'source_row': row._source_row, 'country': row.country, 'month': month,
                            'series_id': series, 'reason': 'conflicting duplicate exact-series month'})
            continue
        # Numerically identical duplicates collapse; keep all original provenance.
        row = group.iloc[0].to_dict(); row.pop('_source_row')
        row['duplicate_observation_count'] = len(group)
        for key in ['source_url', 'source_version', 'published_at', 'fetched_at', 'dimensions']:
            values = sorted({str(v) for v in group[key] if pd.notna(v)})
            row[key] = values[0] if len(values) == 1 else _dump(values)
        accepted.append(row)
    return pd.DataFrame(accepted, columns=MONTHLY_COLUMNS), pd.DataFrame(bad, columns=DIAGNOSTIC_COLUMNS)


def _changes(table, value_column, group_columns, period_column='month'):
    if table.empty:
        return table
    result = table.copy()
    for label in ['mom', 'yoy']:
        result[f'{label}_status'] = pd.Series('', index=result.index, dtype=object)
        result[f'{label}_pct'] = np.nan
    for _, group in result.groupby(group_columns, sort=True, dropna=False):
        values = dict(zip(group[period_column], group[value_column]))
        for i, row in group.iterrows():
            period = pd.Period(row[period_column], freq='M')
            for label, shift in [('mom', 1), ('yoy', 12)]:
                prior = values.get(str(period - shift))
                if not _positive(row[value_column]):
                    result.at[i, f'{label}_status'] = 'current value unavailable'
                elif not _positive(prior):
                    result.at[i, f'{label}_status'] = 'exact comparator unavailable'
                else:
                    result.at[i, f'{label}_pct'] = 100 * (float(row[value_column]) / prior - 1)
                    result.at[i, f'{label}_status'] = 'available'
    return result


def _members(monthly, plan):
    members = []
    first, last = plan['baseline_years']
    for series, group in monthly.groupby('series_id', sort=True):
        row = {k: group.iloc[0][k] for k in IDENTITY}; row['series_id'] = series
        baseline = group[group.month.between(f'{first}-01', f'{last}-12')]
        counts = Counter(baseline.month.str[:4].astype(int))
        eligible = len(baseline) >= plan['minimum_baseline_months'] and all(
            counts[y] >= plan['minimum_months_each_baseline_year'] for y in range(first, last + 1))
        row.update(baseline_months=len(baseline), baseline_year_counts=_dump({str(y): counts[y] for y in range(first, last + 1)}),
                   baseline_geometric_mean=float(np.exp(np.log(baseline.value).mean())) if len(baseline) else np.nan,
                   eligible=eligible, eligibility_reason='eligible' if eligible else 'insufficient fixed baseline coverage', weight=np.nan)
        members.append(row)
    result = pd.DataFrame(members, columns=MEMBER_COLUMNS)
    if result.empty:
        return result
    # A staple with multiple eligible baseline identities is ambiguous. Never
    # choose its most favorable identity or count unit/currency variants twice.
    eligible = result[result.eligible]
    for _, group in eligible.groupby(['country', 'market_id', 'commodity_id'], sort=True):
        if len(group) > 1:
            result.loc[group.index, 'eligible'] = False
            result.loc[group.index, 'eligibility_reason'] = 'multiple baseline-eligible identities for one market/staple'
    for country, group in result[result.eligible].groupby('country', sort=True):
        counts = group.groupby('market_id').size()
        markets = counts[counts >= plan['minimum_staples_per_market']]
        if len(markets) < plan['minimum_markets']:
            result.loc[group.index, 'eligible'] = False
            result.loc[group.index, 'eligibility_reason'] = 'insufficient fixed markets or staples'
            continue
        for market, local in group.groupby('market_id'):
            if market not in markets:
                result.loc[local.index, 'eligible'] = False
                result.loc[local.index, 'eligibility_reason'] = 'insufficient fixed staples in market'
            else:
                result.loc[local.index, 'weight'] = 1 / len(markets) / len(local)
    return result


def _annual(monthly, value_column, by):
    rows = []
    if monthly.empty:
        return pd.DataFrame(columns=ANNUAL_COLUMNS)
    temp = monthly.assign(year=monthly.month.str[:4].astype(int))
    for key, group in temp.groupby(by + ['year'], sort=True):
        if not isinstance(key, tuple): key = (key,)
        row = dict(zip(by + ['year'], key))
        values = group.loc[group[value_column].map(_positive), value_column]
        complete = len(values) == 12 and group.month.nunique() == 12
        row.update(observed_months=len(values), value=float(np.exp(np.log(values).mean())) if complete else np.nan,
                   status='available' if complete else 'requires 12 complete months', yoy_pct=np.nan,
                   yoy_status='exact complete prior year unavailable')
        rows.append(row)
    result = pd.DataFrame(rows)
    for _, group in result.groupby(by, sort=True):
        values = dict(zip(group.year, group.value))
        for i, row in group.iterrows():
            if not _positive(row.value):
                result.at[i, 'yoy_status'] = 'current annual value unavailable'
            elif _positive(values.get(row.year - 1)):
                result.at[i, 'yoy_pct'] = 100 * (row.value / values[row.year - 1] - 1)
                result.at[i, 'yoy_status'] = 'available'
    return result.reindex(columns=ANNUAL_COLUMNS)


def build_tables(observations, as_of, plan=None):
    """Return monthly/annual exact-series changes, fixed baskets and diagnostics.

    ``as_of`` selects only calendar months completed before its local date. It
    does not rewind publication history; source publication/fetch times remain
    attached. Missing basket months remain explicit, with no renormalized weights.
    """
    plan = _plan(plan)
    stamp = pd.Timestamp(as_of)
    if pd.isna(stamp): raise ValueError('as_of must be a valid date')
    if stamp.tzinfo is not None: stamp = stamp.tz_convert('America/Chicago').tz_localize(None)
    cutoff = stamp.to_period('M') - 1
    monthly, diagnostics = _prepare(observations, cutoff)
    members = _members(monthly, plan)
    monthly = _changes(monthly, 'value', ['series_id'])
    if not monthly.empty:
        baseline = members.set_index('series_id').baseline_geometric_mean
        monthly['baseline_geometric_mean'] = monthly.series_id.map(baseline)
        monthly['index_2015_2019'] = 100 * monthly.value / monthly.baseline_geometric_mean
        monthly['basket_member'] = monthly.series_id.isin(members.loc[members.eligible, 'series_id'])
    rows, coverage = [], []
    countries = sorted(set(plan.get('expected_countries', COUNTRIES)) | set(monthly.country))
    for country in countries:
        fixed = members[(members.country == country) & members.eligible] if len(members) else members
        source = monthly[monthly.country == country]
        baseline_source = source[source.month.between(f'{plan["baseline_years"][0]}-01', f'{plan["baseline_years"][1]}-12')]
        missing_baseline_years = [y for y in range(plan['baseline_years'][0], plan['baseline_years'][1] + 1)
                                  if not baseline_source.month.str.startswith(str(y)).any()]
        coverage.append({'country': country, 'valid_series': int(source.series_id.nunique()),
            'valid_monthly_observations': len(source), 'eligible_fixed_members': len(fixed),
            'eligible_fixed_markets': int(fixed.market_id.nunique()),
            'first_observed_month': source.month.min() if len(source) else None,
            'latest_observed_month': source.month.max() if len(source) else None,
            'maximum_series_baseline_months': int(baseline_source.groupby('series_id').size().max()) if len(baseline_source) else 0,
            'baseline_years_without_any_pairs': _dump(missing_baseline_years),
            'status': 'fixed basket defined' if len(fixed) else 'no eligible fixed basket'})
        if fixed.empty: continue
        start = min(f'{plan["baseline_years"][0]}-01', source.month.min())
        lookup = source.set_index(['series_id', 'month']).index_2015_2019.to_dict()
        for period in pd.period_range(start, cutoff, freq='M'):
            month = str(period)
            values = [(r, lookup.get((r.series_id, month))) for r in fixed.itertuples()]
            available = [(r, v) for r, v in values if _positive(v)]
            complete = len(available) == len(fixed)
            market_counts = Counter(r.market_id for r, v in available)
            expected_counts = fixed.groupby('market_id').size().to_dict()
            rows.append({'country': country, 'month': month, 'expected_members': len(fixed),
                'observed_members': len(available), 'member_coverage': len(available) / len(fixed),
                'expected_markets': len(expected_counts),
                'complete_markets': sum(market_counts[k] == v for k, v in expected_counts.items()),
                'index': float(np.exp(sum(r.weight * np.log(v) for r, v in available))) if complete else np.nan,
                'status': 'available' if complete else 'incomplete fixed basket; index withheld'})
    basket = _changes(pd.DataFrame(rows, columns=BASKET_COLUMNS), 'index', ['country'])
    latest = monthly.sort_values(['series_id', 'month']).groupby('series_id', sort=True).tail(1).copy() if len(monthly) else monthly.copy()
    latest['age_months'] = latest.month.map(lambda x: cutoff.ordinal - pd.Period(x, freq='M').ordinal)
    membership = sorted(members.loc[members.eligible, 'series_id']) if len(members) else []
    manifest = {'schema_version': 1, 'as_of': str(stamp.date()), 'last_complete_month': str(cutoff),
        'baseline_years': plan['baseline_years'], 'plan': plan, 'plan_sha256': _hash(plan),
        'fixed_member_ids': membership, 'membership_sha256': _hash(membership),
        'valid_monthly_observations': len(monthly), 'quarantined_rows': len(diagnostics),
        'quarantine_reasons': diagnostics.reason.value_counts().to_dict(),
        'quarantine_scope': 'Derived ratio observations only; raw quotes without a valid matching daily wage are not candidate ratios.',
        'aggregate_label': 'fixed monitored-market purchasing-power index',
        'annual_method': 'geometric mean of all 12 monthly values; exact previous complete year only',
        'ambiguity_rule': 'Exclude market/commodity with multiple baseline-eligible exact identities from basket; keep individual-series results.',
        'publication_scope': 'Reference-period cutoff only. Revised snapshots retain source timestamps; not a release-time or prospective backtest.',
        'membership_scope': 'Fixed across this snapshot by 2015–19 coverage only; historical source revisions can change eligibility, tracked by membership hash.',
        'interpretation': 'Descriptive local purchasing power. No national representativeness, CPI, seasonal adjustment or imputed missing observations.'}
    return {'monthly': monthly.reindex(columns=MONTHLY_COLUMNS), 'latest_series': latest,
            'series_annual': _annual(monthly, 'value', ['country', 'series_id']),
            'basket_members': members, 'basket_monthly': basket,
            'basket_annual': _annual(basket, 'index', ['country']),
            'coverage': pd.DataFrame(coverage), 'diagnostics': diagnostics, 'manifest': manifest}


def _cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def _fmt(value, percent=False):
    if value is None or pd.isna(value): return 'unavailable'
    return f'{value:+.1f}%' if percent else f'{value:,.2f}'


def report_lines(tables):
    """Compact fixed-selection examples; full market-series results stay in tables."""
    lines = ['Food purchasing power uses exact matched WFP retail staple / non-qualified daily-wage series. '
             'MoM and YoY require exact calendar comparators. Completed months only; missing comparisons stay unavailable. '
             'Values describe monitored markets, not national wages or CPI.', '',
             '| Country | Market / staple (currency; quoted food unit) | Month | Kg per daily wage | MoM | YoY |',
             '|---|---|---|---:|---:|---:|']
    latest = tables['latest_series']
    for country in tables['coverage'].country:
        local = latest[latest.country == country]
        if local.empty:
            lines.append(f'| {_cell(country)} | No validated exact pairs | — | unavailable | unavailable | unavailable |')
            continue
        # Select latest month, then first exact series alphabetically, never by outcome.
        local = local[local.month == local.month.max()].sort_values(['market_id', 'commodity', 'commodity_id', 'currency', 'food_unit_original', 'wage_series_signature'])
        row = local.iloc[0]
        lines.append(f'| {_cell(country)} | {_cell(row.market_id)} / {_cell(row.commodity)} ({_cell(row.currency)}; {_cell(row.food_unit_original)}) | {row.month} | {_fmt(row.value)} | {_fmt(row.mom_pct, True)} | {_fmt(row.yoy_pct, True)} |')
    lines += ['', 'Examples are nonrepresentative: alphabetical first market/staple among each country’s latest complete observations. '
              'Full tables preserve wage identity, prices, source timestamps, missing comparators and staleness.', '',
              'Fixed monitored-market purchasing-power index: each baseline-eligible exact series equals 100 at its 2015–19 geometric mean. '
              'Equal market weights, equal fixed-staple weights within each market; every index requires 100% fixed-member coverage. '
              'Annual values require 12 complete months. No seasonal adjustment.', '',
              '| Country | Latest available index month | Index | MoM | YoY | Latest completed-month member coverage |',
              '|---|---|---:|---:|---:|---:|']
    for country in tables['coverage'].country:
        local = tables['basket_monthly'][tables['basket_monthly'].country == country]
        if local.empty:
            lines.append(f'| {_cell(country)} | No eligible fixed basket | unavailable | unavailable | unavailable | 0 members |')
            continue
        current = local.iloc[-1]
        valid = local[local['index'].notna()]
        cov = f'{int(current.observed_members)}/{int(current.expected_members)} ({current.month})'
        if valid.empty:
            lines.append(f'| {_cell(country)} | No complete fixed basket | unavailable | unavailable | unavailable | {cov} |')
        else:
            row = valid.iloc[-1]
            lines.append(f'| {_cell(country)} | {row.month} | {_fmt(row["index"])} | {_fmt(row.mom_pct, True)} | {_fmt(row.yoy_pct, True)} | {cov} |')
    for row in tables['coverage'].itertuples():
        if row.valid_series and not row.eligible_fixed_members:
            missing = ', '.join(str(y) for y in json.loads(row.baseline_years_without_any_pairs)) or 'none'
            lines += ['', f'{_cell(row.country)} basket unavailable: at most {row.maximum_series_baseline_months} baseline months per exact series; '
                      f'baseline years with no matched pairs: {missing}. Required: 36 months total and at least 6 in every year from 2015 through 2019.']
    lines += ['', f'Validation excluded {tables["manifest"]["quarantined_rows"]:,} rows; exact reasons and baseline eligibility remain in diagnostics. '
              'Historical revised snapshots are exploratory; reference-period cutoffs do not reconstruct information available at release time.']
    return lines


def markdown_report(observations, as_of, plan=None):
    """Convenience report helper accepting the same inputs as build_tables."""
    return '\n'.join(report_lines(build_tables(observations, as_of, plan)))
