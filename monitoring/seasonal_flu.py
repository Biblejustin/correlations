"""Descriptive WHO sentinel positivity against frozen prior-season references.

Calendar completeness and specimen thresholds do not establish surveillance-site
coverage. Source provisional flags remain visible. These calculations use the
current revised snapshot, not historical release-time forecasting information.
"""
from __future__ import annotations

import argparse
import copy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median

import pandas as pd

_EXTENSION_PLAN = json.loads(Path(__file__).with_name('extension_plan.json').read_text())
PLAN = copy.deepcopy(_EXTENSION_PLAN['seasonal_flu'])
LIMITATIONS = [
    'Descriptive positivity differences, not outbreak diagnoses, calibrated p-values or population infection prevalence.',
    'Calendar-complete, sufficiently tested observations do not establish reporting-site coverage; site coverage remains unverified.',
    'Universal source provisional flags indicate revisable surveillance observations, not proof that the observation week is partial.',
    'Historical references use this revised snapshot. They do not reconstruct information available when each historical week was first reported.',
    'Missing, invalid, partial, projected and low-testing weeks are unavailable; absent weeks are never filled with zero.',
]
TABLE_COLUMNS = ['country', 'stream_id', 'source_id', 'source_version', 'dimensions', 'source_url',
                 'period_start', 'period_end', 'iso_year', 'iso_week', 'latest_expected_week',
                 'status', 'numerator', 'denominator', 'observed_positivity', 'baseline_positivity',
                 'difference_percentage_points', 'positivity_ratio', 'ratio_status',
                 'qualified_baseline_windows', 'required_baseline_windows', 'planned_baseline_windows',
                 'eligible_baseline_weeks', 'baseline_specimens', 'source_provisional',
                 'observed_period_end', 'reporting_site_coverage']
QUALITY_COLUMNS = ['source_row', 'country', 'stream_id', 'period_start', 'period_end', 'reason', 'source_provisional']
WINDOW_COLUMNS = ['country', 'stream_id', 'target_start', 'target_iso_year', 'target_iso_week',
                  'baseline_center_iso_year', 'baseline_center_iso_week', 'week53_mapped_to52',
                  'window_start', 'window_end', 'expected_weeks', 'eligible_weeks', 'qualified',
                  'positive_specimens', 'tested_specimens', 'positivity', 'excluded_week_reasons']


def _plan(plan):
    result = copy.deepcopy(PLAN)
    if plan is not None:
        unknown = set(plan) - set(PLAN)
        if unknown:
            raise ValueError(f'Unknown seasonal-flu plan fields: {sorted(unknown)}')
        result.update(copy.deepcopy(plan))
    numeric = ['target_weeks', 'reporting_lag_days', 'minimum_tested_specimens', 'baseline_prior_iso_years',
               'seasonal_half_window_weeks', 'minimum_weeks_per_baseline_window', 'minimum_baseline_windows']
    for key in numeric:
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < (0 if key in {'reporting_lag_days', 'seasonal_half_window_weeks'} else 1):
            raise ValueError(f'Invalid seasonal-flu plan value: {key}')
    if result['minimum_weeks_per_baseline_window'] > 2 * result['seasonal_half_window_weeks'] + 1:
        raise ValueError('Minimum baseline weeks exceed the seasonal window size')
    if result['minimum_baseline_windows'] > result['baseline_prior_iso_years']:
        raise ValueError('Minimum baseline windows exceed prior years')
    countries = result['expected_countries']
    if not isinstance(countries, list) or any(not isinstance(item, str) or not item for item in countries) or len(set(countries)) != len(countries):
        raise ValueError('Expected countries must be distinct nonempty country codes')
    for key in set(PLAN) - set(numeric) - {'expected_countries'}:
        if result[key] != PLAN[key]:
            raise ValueError(f'Unsupported change to frozen seasonal-flu method: {key}')
    return result


def _as_of(value):
    if value is None:
        return pd.Timestamp(datetime.now(timezone.utc))
    day_only = (isinstance(value, date) and not isinstance(value, datetime)) or (isinstance(value, str) and bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)))
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError) as error:
        raise ValueError('as_of must be an ISO date or timestamp') from error
    if pd.isna(stamp):
        raise ValueError('as_of cannot be missing')
    stamp = stamp.tz_localize('UTC') if stamp.tzinfo is None else stamp.tz_convert('UTC')
    return stamp + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1) if day_only else stamp


def _timestamp(value):
    if value is None or (isinstance(value, float) and math.isnan(value)) or str(value).strip() == '':
        return None
    try:
        result = pd.Timestamp(value)
        if pd.isna(result):
            return None
        return result.tz_localize('UTC') if result.tzinfo is None else result.tz_convert('UTC')
    except (TypeError, ValueError):
        return None


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _boolean(value):
    if value is True or str(value).strip().lower() in {'true', '1', 'yes'}:
        return True
    if value is False or str(value).strip().lower() in {'false', '0', 'no'}:
        return False
    return None


def _text(value):
    return '' if value is None or (isinstance(value, float) and math.isnan(value)) else str(value)


def _stream(country, source, version, dimensions):
    canonical_dimensions = json.dumps(dimensions, sort_keys=True, separators=(',', ':'), allow_nan=False)
    identity = json.dumps([country, source, version, canonical_dimensions], separators=(',', ':'))
    return hashlib.sha256(identity.encode()).hexdigest()[:20], canonical_dimensions


def _prepare(observations, as_of, latest_end, plan):
    """Validate rows without pooling distinct source/dimension streams or duplicates."""
    streams, quality = {}, []
    if observations.empty:
        observations = pd.DataFrame(columns=['metric', 'source_id'])
    if not {'metric', 'source_id'} <= set(observations):
        raise ValueError('Seasonal flu requires normalized metric/source_id columns')
    selected = observations[observations['metric'].eq('influenza_positivity') & observations['source_id'].astype(str).str.lower().eq('who')]
    for position, (_, row) in enumerate(selected.iterrows(), 1):
        country = _text(row.get('country'))
        note = dict(source_row=position, country=country, stream_id='', period_start=_text(row.get('period_start')),
                    period_end=_text(row.get('period_end')), reason='', source_provisional=_boolean(row.get('provisional')))
        try:
            dimensions = json.loads(row['dimensions']) if isinstance(row.get('dimensions'), str) else row.get('dimensions')
            if not isinstance(dimensions, dict):
                raise ValueError('not an object')
            if str(dimensions.get('surveillance_origin', '')).strip().upper() != 'SENTINEL':
                note['reason'] = 'excluded_non_sentinel'; quality.append(note); continue
            stream_id, dimensions_json = _stream(country, _text(row['source_id']), _text(row.get('source_version')), dimensions)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            note['reason'] = 'invalid_dimensions'; quality.append(note); continue
        if not country:
            note['reason'] = 'missing_country'; quality.append(note); continue
        note['stream_id'] = stream_id
        stream = streams.setdefault(stream_id, dict(country=country, stream_id=stream_id, source_id=_text(row['source_id']),
                                                   source_version=_text(row.get('source_version')), dimensions=dimensions_json,
                                                   source_urls=set(), weeks={}))
        if _text(row.get('source_url')):
            stream['source_urls'].add(_text(row['source_url']))
        start, end = _timestamp(row.get('period_start')), _timestamp(row.get('period_end'))
        reason = ''
        bucket = start.date() - timedelta(days=start.weekday()) if start is not None else None
        if start is None or end is None:
            reason = 'invalid_period'
        elif start != start.normalize() or end != end.normalize() or start.weekday() != 0 or end != start + pd.Timedelta(days=6):
            reason = 'incomplete_or_invalid_iso_week'
        elif end + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1) > as_of:
            reason = 'calendar_week_not_complete'
        elif end.date() > latest_end:
            reason = 'reporting_lag'
        if not reason and (_boolean(row.get('projected')) is True or str(dimensions.get('type', 'current')).strip().lower() not in {'current', 'actual', 'observed'}):
            reason = 'projected_observation'
        if not reason and (any(_boolean(value) is True for value in [row.get('partial_week'), dimensions.get('partial_week'), dimensions.get('partial')])
                           or any(_boolean(value) is False for value in [row.get('reporting_complete'), dimensions.get('reporting_complete')])):
            reason = 'explicit_partial_reporting'
        if not reason and (_text(row.get('unit')) != 'positive_fraction' or _text(row.get('frequency')) != 'weekly'):
            reason = 'incompatible_unit_or_frequency'
        positive, tested = _number(row.get('numerator')), _number(row.get('denominator'))
        positivity = None
        if not reason:
            if positive is None or tested is None:
                reason = 'missing_specimen_counts'
            elif positive < 0 or tested <= 0 or positive > tested or not positive.is_integer() or not tested.is_integer():
                reason = 'invalid_specimen_counts'
            elif tested < plan['minimum_tested_specimens']:
                reason = 'low_testing'
            else:
                positivity = positive / tested
                stated = _number(row.get('value'))
                if stated is not None and not math.isclose(stated, positivity, rel_tol=1e-9, abs_tol=1e-12):
                    reason = 'inconsistent_reported_positivity'
        if not reason:
            for field in ('published_at', 'fetched_at'):
                value = row.get(field)
                stamp = _timestamp(value)
                if _text(value) and stamp is None:
                    reason = 'invalid_availability_timestamp'; break
                if stamp is not None and stamp > as_of:
                    reason = 'not_available_as_of'; break
        note['reason'] = reason or 'eligible'
        quality.append(note)
        record = dict(reason=reason, positive=positive, tested=tested, positivity=positivity if not reason else None,
                      provisional=_boolean(row.get('provisional')), end=end.date() if end is not None else None,
                      source_url=_text(row.get('source_url')), quality=note)
        if bucket is not None:
            existing = stream['weeks'].get(bucket)
            if existing is not None:
                existing['reason'] = 'duplicate_stream_week'; existing['positivity'] = None
                existing['quality']['reason'] = 'duplicate_stream_week'
                note['reason'] = 'duplicate_stream_week'
            else:
                stream['weeks'][bucket] = record
    present_countries = {stream['country'] for stream in streams.values()}
    for country in plan['expected_countries']:
        if country not in present_countries:
            stream_id, dimensions = _stream(country, 'who', 'unavailable', {'surveillance_origin': 'SENTINEL'})
            streams[stream_id] = dict(country=country, stream_id=stream_id, source_id='who', source_version='unavailable',
                                      dimensions=dimensions, source_urls=set(), weeks={})
    return streams, quality


def _historical_windows(stream, target, plan):
    target_year, target_week, _ = target.isocalendar()
    output = []
    half_width = plan['seasonal_half_window_weeks']
    for year in range(target_year - plan['baseline_prior_iso_years'], target_year):
        last_week = date(year, 12, 28).isocalendar().week
        center_week = min(target_week, last_week)
        center = date.fromisocalendar(year, center_week, 1)
        eligible, reasons = [], {}
        for offset in range(-half_width, half_width + 1):
            week = center + timedelta(weeks=offset)
            record = stream['weeks'].get(week)
            if week.isocalendar().year >= target_year or week + timedelta(days=6) >= target:
                reason = 'not_strictly_prior_target_iso_year'
            elif record is None:
                reason = 'unobserved_week'
            else:
                reason = record['reason']
            if reason:
                reasons[reason] = reasons.get(reason, 0) + 1
            else:
                eligible.append(record)
        qualifies = len(eligible) >= plan['minimum_weeks_per_baseline_window']
        positive = sum(record['positive'] for record in eligible) if eligible else None
        tested = sum(record['tested'] for record in eligible) if eligible else None
        output.append(dict(country=stream['country'], stream_id=stream['stream_id'], target_start=target.isoformat(),
                           target_iso_year=target_year, target_iso_week=target_week, baseline_center_iso_year=year,
                           baseline_center_iso_week=center_week, week53_mapped_to52=target_week == 53 and center_week == 52,
                           window_start=(center - timedelta(weeks=half_width)).isoformat(),
                           window_end=(center + timedelta(weeks=half_width, days=6)).isoformat(),
                           expected_weeks=2 * half_width + 1, eligible_weeks=len(eligible), qualified=qualifies,
                           positive_specimens=positive, tested_specimens=tested,
                           positivity=positive / tested if qualifies else None,
                           excluded_week_reasons=json.dumps(reasons, sort_keys=True, separators=(',', ':'))))
    return output


def seasonal_flu(observations, as_of=None, plan=None):
    """Return a weekly DataFrame; JSON-safe coverage/quality diagnostics live in attrs.

    ``plan`` is the seasonal_flu subplan from extension_plan.json (or explicit
    numeric/country overrides, recorded in the output hash). Date-only as_of
    includes that entire UTC date; a supplied timestamp is honored exactly.
    """
    plan = _plan(plan)
    as_of = _as_of(as_of)
    elapsed_cutoff = as_of - pd.Timedelta(days=plan['reporting_lag_days'])
    cutoff = elapsed_cutoff.date()
    latest_end = cutoff - timedelta(days=(cutoff.weekday() + 1) % 7)
    # Period endpoints name the whole Sunday, not its midnight. An exact
    # timestamp early Sunday cannot yet include that week plus the full lag.
    inclusive_end = pd.Timestamp(latest_end, tz='UTC') + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    if inclusive_end > elapsed_cutoff:
        latest_end -= timedelta(weeks=1)
    latest_start = latest_end - timedelta(days=6)
    targets = [latest_start - timedelta(weeks=offset) for offset in reversed(range(plan['target_weeks']))]
    streams, quality = _prepare(observations, as_of, latest_end, plan)
    rows, all_windows = [], []
    for stream in sorted(streams.values(), key=lambda value: (value['country'], value['stream_id'])):
        for target in targets:
            record = stream['weeks'].get(target)
            current_reason = record['reason'] if record is not None else 'unobserved_week'
            windows = _historical_windows(stream, target, plan)
            all_windows.extend(windows)
            qualified = [window for window in windows if window['qualified']]
            enough = len(qualified) >= plan['minimum_baseline_windows']
            baseline = median(window['positivity'] for window in qualified) if enough else None
            current = record['positivity'] if record is not None else None
            status = current_reason or ('available' if enough else 'insufficient_baseline')
            difference = 100 * (current - baseline) if status == 'available' else None
            ratio = current / baseline if status == 'available' and baseline > 0 else None
            rows.append(dict(country=stream['country'], stream_id=stream['stream_id'], source_id=stream['source_id'],
                             source_version=stream['source_version'], dimensions=stream['dimensions'],
                             source_url=record['source_url'] if record is not None else ';'.join(sorted(stream['source_urls'])),
                             period_start=target.isoformat(), period_end=(target + timedelta(days=6)).isoformat(),
                             iso_year=target.isocalendar().year, iso_week=target.isocalendar().week,
                             latest_expected_week=target == latest_start, status=status,
                             numerator=record['positive'] if record is not None else None,
                             denominator=record['tested'] if record is not None else None,
                             observed_positivity=current, baseline_positivity=baseline,
                             difference_percentage_points=difference, positivity_ratio=ratio,
                             ratio_status='available' if ratio is not None else 'baseline_zero' if status == 'available' and baseline == 0 else 'unavailable',
                             qualified_baseline_windows=len(qualified), required_baseline_windows=plan['minimum_baseline_windows'],
                             planned_baseline_windows=plan['baseline_prior_iso_years'],
                             eligible_baseline_weeks=sum(window['eligible_weeks'] for window in qualified),
                             baseline_specimens=sum(window['tested_specimens'] for window in qualified) if qualified else None,
                             source_provisional=record['provisional'] if record is not None else None,
                             observed_period_end=record['end'].isoformat() if record is not None and record['end'] is not None else '',
                             reporting_site_coverage='unverified'))
    table = pd.DataFrame(rows, columns=TABLE_COLUMNS)
    table.attrs = dict(schema_version=1, as_of_utc=as_of.isoformat(), latest_expected_week_start=latest_start.isoformat(),
                       latest_expected_week_end=latest_end.isoformat(), plan=plan,
                       plan_sha256=hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                       design_fixed_at_utc=_EXTENSION_PLAN['design_fixed_at_utc'], baseline_windows=all_windows,
                       row_quality=quality, limitations=LIMITATIONS,
                       input_rows=len(observations), surveillance_streams=len(streams))
    return table


def report_lines(table, heading='Seasonal sentinel influenza'):
    """Render the latest expected week per stream, including missing countries."""
    lines = [f'## {heading}', ''] if heading else []
    if table.empty:
        return lines + ['Unavailable: no sentinel surveillance streams in the declared scope.']
    latest = table[table['latest_expected_week']].sort_values(['country', 'stream_id'])
    lines += ['| Country / stream | Expected ISO week | Tested | Positivity | Seasonal baseline | Difference | Status |',
              '|---|---|---:|---:|---:|---:|---|']
    def number(value, kind):
        if pd.isna(value):
            return '—'
        return f'{value:,.0f}' if kind == 'count' else f'{100*value:.1f}%' if kind == 'fraction' else f'{value:+.1f} pp'
    for _, row in latest.iterrows():
        label = str(row['country']) + ' / ' + str(row['stream_id'])[:8]
        status = str(row['status']).replace('_', ' ')
        if row['source_provisional'] is True or _boolean(row['source_provisional']) is True:
            status += '; provisional'
        lines.append(f'| {label} | {int(row.iso_year)}-W{int(row.iso_week):02d} | {number(row.denominator,"count")} | '
                     f'{number(row.observed_positivity,"fraction")} | {number(row.baseline_positivity,"fraction")} | '
                     f'{number(row.difference_percentage_points,"difference")} | {status} |')
    lines += ['', 'References use only prior ISO years, with minimum specimen/week and historical-window coverage rules. '
              'Latest expected weeks remain visible when data are missing. Reporting-site coverage is unverified; '
              'these are descriptive positivity differences, not outbreak diagnoses or calibrated p-values.']
    return lines


def write_outputs(table, output_dir):
    """Write standalone tables and a manifest; unavailable numeric cells stay blank."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frames = {'seasonal_flu_weekly.csv': table,
              'seasonal_flu_baseline_windows.csv': pd.DataFrame(table.attrs['baseline_windows'], columns=WINDOW_COLUMNS),
              'seasonal_flu_row_quality.csv': pd.DataFrame(table.attrs['row_quality'], columns=QUALITY_COLUMNS)}
    payloads = {name: frame.to_csv(index=False, lineterminator='\n').encode() for name, frame in frames.items()}
    payloads['seasonal_flu.md'] = ('\n'.join(report_lines(table)) + '\n').encode()
    manifest = {key: value for key, value in table.attrs.items() if key not in {'baseline_windows', 'row_quality'}}
    manifest['status_counts'] = table['status'].value_counts().to_dict()
    manifest['output_sha256'] = {name: hashlib.sha256(content).hexdigest() for name, content in payloads.items()}
    payloads['seasonal_flu_manifest.json'] = (json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    for name, content in payloads.items():
        path = output / name
        if not path.exists() or path.read_bytes() != content:
            temporary = path.with_name(path.name + '.tmp')
            temporary.write_bytes(content)
            temporary.replace(path)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observations', nargs='+', required=True, type=Path)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--plan', type=Path)
    args = parser.parse_args()
    selected_plan = json.loads(args.plan.read_text()) if args.plan else None
    if selected_plan and 'seasonal_flu' in selected_plan:
        selected_plan = selected_plan['seasonal_flu']
    observations = pd.concat([pd.read_csv(path) for path in args.observations], ignore_index=True)
    result = seasonal_flu(observations, args.as_of, selected_plan)
    write_outputs(result, args.output)
    print('\n'.join(report_lines(result)))
