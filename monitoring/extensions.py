"""Run separate climate, seasonal flu and purchasing-power monitors."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from monitoring import affordability, climate_controls, seasonal_flu
from monitoring.climate_indices import ROOT as CLIMATE_ROOT, load_snapshot
from monitoring.feeds import BASE
from source_tracking import file_digest, write_json_if_changed
from statistical_helpers import last_complete_year


def load_global_series(root=BASE, end_year=None):
    """Use the original matrix's exact loaders, transformations and source scope."""
    from correlate_events import (load_yearly_quakes_m7, load_yearly_war_deaths_active,
        load_yearly_famine_deaths_wpf, load_yearly_flood_deaths, load_yearly_pandemic_deaths,
        load_yearly_volcanoes, load_yearly_cyclone_deaths, load_yearly_flares_x1,
        load_yearly_terrorism_deaths, load_yearly_stock_drawdown_intensity)
    root = Path(root)
    end = min(last_complete_year(), end_year if end_year is not None else last_complete_year())
    data = root/'data'
    return {
        'M>=7 quakes': (load_yearly_quakes_m7(root.parent/'earthquakes/quakes_1900.sqlite', 1900, end), 'quakes_m7'),
        'War deaths log10': (load_yearly_war_deaths_active(data/'wars.csv', 1900, end, log10_transform=True), 'wars_global'),
        'Famine deaths log10 (WPF)': (load_yearly_famine_deaths_wpf(data/'famine_deaths_by_year.csv', 1900, end, log10_transform=True), 'famines'),
        'Flood deaths log10': (load_yearly_flood_deaths(data/'floods.csv', 1900, end, log10_transform=True), 'floods'),
        'Pandemic deaths log10': (load_yearly_pandemic_deaths(data/'pandemics.csv', 1900, end, log10_transform=True), 'pandemics'),
        'Volcanoes VEI>=5': (load_yearly_volcanoes(data/'volcanoes.csv', 1900, end, vei_min=5), 'volcanoes'),
        'Cyclone deaths log10': (load_yearly_cyclone_deaths(data/'cyclones.csv', 1900, end, log10_transform=True), 'cyclones'),
        'X1+ flares': (load_yearly_flares_x1(data/'flares_xclass.csv', 1976, end), 'flares_x'),
        'Terrorism deaths log10': (load_yearly_terrorism_deaths(data/'terrorism.csv', 1970, end, log10_transform=True), 'terrorism'),
        'Stock crash intensity log10': (load_yearly_stock_drawdown_intensity(data/'stock_crashes.csv', 1900, end, log10_transform=True), 'stock_crashes'),
    }


def _fingerprint(frame):
    return hashlib.sha256(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes()).hexdigest()


def run(observations, panel, output, *, as_of=None, climate_root=CLIMATE_ROOT, global_series=None):
    """All outputs use one report date. Any source/analysis failure stops publication."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    value = as_of if as_of is not None else dt.datetime.now(ZoneInfo('America/Chicago'))
    stamp = pd.Timestamp(value)
    stamp = stamp.tz_localize('America/Chicago') if stamp.tzinfo is None else stamp.tz_convert('America/Chicago')
    # Date-only exports include that entire Chicago date; routine refreshes use
    # their actual timestamp, including UTC retrievals after local midnight UTC.
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime) or isinstance(value, str) and len(value) == 10:
        stamp = stamp + pd.DateOffset(days=1) - pd.Timedelta(nanoseconds=1)
    today = stamp.date()
    climate, source = load_snapshot(climate_root)
    series = load_global_series(end_year=today.year-1) if global_series is None else global_series
    global_table = climate_controls.global_climate_sensitivity(series, climate['annual.csv'], end_year=today.year-1)
    regional_table = climate_controls.regional_climate_sensitivity(panel, climate['annual.csv'], end_year=today.year-1)
    climate_controls.write_outputs(global_table, regional_table, output)
    flu = seasonal_flu.seasonal_flu(observations, as_of=stamp)
    seasonal_flu.write_outputs(flu, output)
    food = affordability.build_tables(observations, as_of=today)
    for name, table in food.items():
        if isinstance(table, pd.DataFrame):
            table.to_csv(output/f'affordability_{name}.csv', index=False)
    write_json_if_changed(output/'affordability_manifest.json', food['manifest'])
    (output/'affordability.md').write_text('\n'.join(affordability.report_lines(food))+'\n')
    lines = ['# Climate, respiratory and purchasing-power monitors', '', f'Reference date: {today} (America/Chicago). Exact cutoff: {stamp.isoformat()}.', '',
             'Historical exploratory extensions. Source revisions are retained; reference dates do not reconstruct release-time availability. '
             'These measures support observation and comparison, not prophetic-fulfillment claims.', '',
             '## Ocean climate observations', '',
             '| Index | Latest complete observation window | Value, °C anomaly | Product |',
             '|---|---|---:|---|']
    for name, table in [('rni', climate['monthly.csv'].query("index == 'rni'")),
                        ('dmi', climate['monthly.csv'].query("index == 'dmi'")),
                        ('roni', climate['roni_seasonal.csv'])]:
        rows = table[table.usable & (pd.to_datetime(table.period_end).dt.date <= today)].sort_values('period_end')
        if rows.empty:
            lines.append(f'| {name.upper()} | unavailable | — | {source["versions"][name]} |')
        else:
            row = rows.iloc[-1]
            lines.append(f'| {name.upper()} | {row.period_start}–{row.period_end} | {row.value:+.2f} | {row.source_version} |')
    annual = climate['annual.csv'][climate['annual.csv'].year.lt(today.year)]
    if annual.empty:
        raise ValueError('No complete paired climate years precede report date')
    lines += ['', f'Paired complete calendar years: {int(annual.year.min())}–{int(annual.year.max())} ({len(annual)} years). '
              'Monthly RNI supplies the annual ENSO control; seasonal RONI spans its full three-month window. '
              'DMI measures the Indian Ocean west-minus-east sea-surface-temperature gradient. '
              'CPC values may revise; DMI is preliminary. No partial annual values or inferred local rainfall.', '',
              '[NOAA CPC definitions](https://www.cpc.ncep.noaa.gov/data/indices/) · '
              '[NOAA PSL DMI definition](https://psl.noaa.gov/data/timeseries/month/DMI/) · '
              '[Versioned source manifest](../../../data/climate_indices/manifest.json)', '',
              '## Climate-control sensitivity', '']
    lines += climate_controls.report_lines(global_table, regional_table)
    selected = pd.concat([global_table[global_table.reject_fdr], regional_table[regional_table.reject_fdr]], ignore_index=True)
    lines += ['', '| Family / country | Predictor → response | Lag | Fit | Years | Partial r | BH q |',
              '|---|---|---:|---|---|---:|---:|']
    for row in selected.itertuples():
        lines.append(f'| {row.family} / {row.country} | {row.predictor} → {row.response} | {row.lag_years} | '
                     f'{row.fit} | {int(row.response_start_year)}–{int(row.response_end_year)} | {row.partial_r:+.3f} | {row.q_family:.4f} |')
    if selected.empty:
        lines.append('| Both fixed families | No fit passes BH q < 0.05 | — | — | — | — | — |')
    lines += ['', 'Table lists all passing fits; [all 90 global fits](global_climate_sensitivity.csv) and '
              '[all 144 regional fits](regional_climate_sensitivity.csv) preserve every planned result and unavailable cell. '
              'A change after adjustment does not establish mediation or causation. These HAC sensitivities do not replace the original block-null tests.', '']
    if len(selected):
        lines += [f'{len(selected)} passing fits describe {selected.pair_id.nunique()} distinct country/pair/lag associations. '
                  'Two fits for one association are sensitivity comparisons, not independent discoveries. '
                  'Refugee-origin stock change is a net stock difference, not newly displaced people.', '']
    lines += seasonal_flu.report_lines(flu)
    lines += ['', '[Weekly differences and eligibility](seasonal_flu_weekly.csv) · '
              '[Historical seasonal windows](seasonal_flu_baseline_windows.csv) · '
              '[WHO source](https://xmart-api-public.who.int/FLUMART/VIW_FNT)', '', '## Food purchasing power', '']
    lines += affordability.report_lines(food)
    lines += ['', '[Exact monthly series](affordability_monthly.csv) · [Fixed basket membership](affordability_basket_members.csv) · '
              '[Monthly indices](affordability_basket_monthly.csv) · [Coverage](affordability_coverage.csv)', '',
              'Definitions and frozen comparison rules: [extension plan](../../../monitoring/extension_plan.json) and '
              '[monitoring documentation](../../../MONITORING.md).']
    (output/'extensions_report.md').write_text('\n'.join(lines)+'\n')
    plan_path = Path(__file__).with_name('extension_plan.json')
    manifest = {'schema_version': 1, 'report_date': str(today), 'as_of_utc': stamp.tz_convert('UTC').isoformat(), 'report_timezone': 'America/Chicago',
                'extension_plan_sha256': file_digest(plan_path), 'climate_snapshot_id': source['snapshot_id'],
                'climate_manifest_sha256': file_digest(Path(climate_root)/'manifest.json'),
                'observation_rows': len(observations), 'observation_fingerprint': _fingerprint(observations),
                'annual_panel_fingerprint': _fingerprint(panel),
                'global_series_fingerprints': {name: _fingerprint(value[0] if isinstance(value, tuple) else value) for name, value in series.items()},
                'global_planned_fits': len(global_table), 'regional_planned_fits': len(regional_table),
                'global_passing_fits': int(global_table.reject_fdr.sum()),
                'regional_passing_fits': int(regional_table.reject_fdr.sum()),
                'flu_expected_week_end': flu.attrs['latest_expected_week_end'],
                'affordability_last_complete_month': food['manifest']['last_complete_month'],
                'outputs': {p.name: file_digest(p) for p in sorted(output.iterdir()) if p.is_file() and p.name != 'extensions_manifest.json'}}
    write_json_if_changed(output/'extensions_manifest.json', manifest)
    return manifest


def main():
    import argparse
    from monitoring.analysis import load_observations, build_annual_panel
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data-dir', type=Path, default=BASE/'data/monitoring')
    ap.add_argument('--out', type=Path, default=BASE/'results/monitoring/extensions')
    ap.add_argument('--as-of', help='Reference date YYYY-MM-DD; historical snapshots may contain later revisions')
    args = ap.parse_args()
    observations = load_observations(args.data_dir)
    panel = build_annual_panel(observations, as_of=args.as_of)
    result = run(observations, panel, args.out, as_of=args.as_of)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
