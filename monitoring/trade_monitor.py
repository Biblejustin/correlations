"""Publish separate trade and food-price monitoring with retained source evidence."""
from __future__ import annotations
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import pandas as pd
from monitoring import economic_sources, trade_sources, trade_analysis, climate_indices
from monitoring.analysis import load_observations
from monitoring.extensions import _fingerprint
from monitoring.feeds import BASE
from source_tracking import file_digest, write_json_if_changed


def run(observations, output, *, as_of=None, shipping_root=trade_sources.ROOT,
        economic_root=economic_sources.ROOT, climate_root=climate_indices.ROOT):
    stamp=pd.Timestamp(as_of if as_of is not None else dt.datetime.now(ZoneInfo('America/Chicago')))
    stamp=stamp.tz_localize('America/Chicago') if stamp.tzinfo is None else stamp.tz_convert('America/Chicago')
    shipping,shipping_source=trade_sources.load_snapshot(shipping_root)
    economics,economic_source=economic_sources.load_snapshot(economic_root)
    climate,climate_source=climate_indices.load_snapshot(climate_root)
    food,members,diagnostics=trade_analysis.monthly_food(observations,stamp)
    transport=trade_analysis.monthly_shipping(shipping['daily.csv'],stamp)
    rates=trade_analysis.monthly_fx(economics['official_fx_monthly.csv'],stamp)
    fits=trade_analysis.compare(food,transport,rates,climate['monthly.csv'],stamp)
    cereal=economics['cereal_dependence.csv'].copy()
    cereal=cereal[cereal.usable & (pd.to_datetime(cereal.period_end)<stamp.tz_localize(None).normalize())]
    latest_cereal=cereal.sort_values('period_end').groupby('country').tail(1)
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    tables={'food_monthly.csv':food,'food_members.csv':members,'food_diagnostics.csv':diagnostics,
            'shipping_monthly.csv':transport,'official_fx_monthly.csv':rates,'trade_food_tests.csv':fits,
            'cereal_dependence.csv':cereal}
    for name,frame in tables.items():frame.to_csv(output/name,index=False)
    passing=fits[fits.reject_fdr];eligible=fits[fits.status.eq('eligible')]
    lines=['# Trade, currencies and food-price monitoring','',f'Reference cutoff: {stamp.isoformat()} (America/Chicago).','',
        f'{len(fits)} frozen comparisons; {len(eligible)} estimable fits; {len(passing)} pass BH q < 0.05, '
        f'covering {passing.pair_id.nunique()} distinct country/predictor/lag cells. Two fits of one cell are related sensitivities.', '',
        'Historical exploratory associations support observation, not causal or prophetic-fulfillment claims. '
        'Sources can revise; these snapshots do not reconstruct what was known in each historical month.', '',
        '## Shipping observations','',
        '| Chokepoint | Latest eligible month | Mean estimated transit, metric tons/day | YoY decline |',
        '|---|---|---:|---:|']
    for name in trade_analysis.SHIPPING_NAMES.values():
        group=transport[transport.name.eq(name)&transport.daily_mean_tons.notna()].sort_values('month')
        if group.empty:lines.append(f'| {name} | Unavailable | — | — |');continue
        row=group.iloc[-1];change=f'{100*row.transit_decline_yoy:+.1f}%' if pd.notna(row.transit_decline_yoy) else 'Unavailable'
        lines.append(f'| {name} | {row.month} | {row.daily_mean_tons:,.0f} | {change} |')
    lines += ['', 'PortWatch estimates payload-weighted vessel transit from AIS, across all vessel classes. '
        'They do not measure grain cargo or a country’s imports. Suez and Bab el-Mandeb often describe the same route. '
        'Every calendar day is required; seven elapsed days after month end are excluded by this project. '
        'This delay does not make preliminary IMF estimates final. Missing source days remain missing.', '',
        '[IMF PortWatch daily source](https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/Daily_Chokepoints_Data/FeatureServer/0) · '
        '[Source manifest](../../../data/trade_shipping/manifest.json) · [All monthly coverage](shipping_monthly.csv)', '',
        '## Currency and cereal-import context','',
        '| Country | Latest official FX month / YoY | Latest cereal-dependence window / ratio | Fixed food-series currencies |',
        '|---|---|---|---|']
    for country in trade_analysis.COUNTRIES:
        fx=rates[rates.country.eq(country)&rates.official_fx_log_yoy.notna()].sort_values('month')
        fx_label=f'{fx.iloc[-1].month} / {fx.iloc[-1].official_fx_yoy_pct:+.1f}%' if len(fx) else 'Unavailable'
        grain=latest_cereal[latest_cereal.country.eq(country)]
        grain_label=f'{int(grain.iloc[0].start_year)}–{int(grain.iloc[0].end_year)} / {grain.iloc[0].value:.1f}% (flag {grain.iloc[0].flag})' if len(grain) else 'Unavailable'
        local=food[food.country.eq(country)].iloc[-1];currency=local.currencies or 'No eligible basket'
        if local.expected_members and not local.fx_currency_compatible:currency+='; incompatible with official FX'
        lines.append(f'| {country} | {fx_label} | {grain_label} | {currency} |')
    lines += ['', 'Positive FX change means official local-currency depreciation against USD. Official rates may differ materially from retail or parallel-market rates. '
        'Only explicitly monthly World Bank GEM DPANUSLCU observations are used. A food basket must use one verified matching currency; '
        'missing countries, months and incompatible baskets stay unavailable.', '',
        'FAOSTAT cereal dependence remains a full three-year average: 100 × (imports − exports) / (production + imports − exports). '
        'Negative values indicate net exports. It supplies descriptive context, never a monthly predictor or grain-shipment estimate. '
        'All periods and source flags remain in the source archive.', '',
        '[World Bank GEM source](https://api.worldbank.org/v2/indicator/DPANUSLCU?format=json) · '
        '[FAOSTAT food-security source](https://www.fao.org/faostat/en/#data/FS) · '
        '[Versioned economic sources](../../../data/economic_sources/manifest.json)', '',
        '## Fixed comparison family','',
        'Eight countries × four predictors × lags 0, 1 and 3 months × two fits = 192 tests. '
        'Positive lag pairs an earlier predictor month with a later food-price response. Both fits use the same longest contiguous complete span, '
        'at least 60 months and eight residual degrees of freedom. Missing tests remain in BH as p = 1.', '',
        'Food response is the country median of exact-series log year-on-year retail changes. Membership requires at least 24 observed months in 2015–2019; '
        'each month requires at least three series and 70% of fixed membership. This monitored-market basket is not CPI. '
        'Baseline controls include trend and calendar-month indicators. Adjustment adds RNI, DMI and applicable official FX controls in predictor and response months. '
        'HAC uses 12 Bartlett lags, finite-sample correction and Student-t inference. Overlapping YoY windows and common crisis shocks limit inference.', '',
        '| Country | Predictor | Lag months | Fit | Sample | Partial r | BH q |',
        '|---|---|---:|---|---|---:|---:|']
    for row in passing.itertuples():
        lines.append(f'| {row.country} | {row.predictor} | {row.lag_months} | {row.fit} | {row.sample_start}–{row.sample_end} ({row.n}) | {row.partial_r:+.3f} | {row.q_family:.5f} |')
    if passing.empty:lines.append('| All countries | No fit passes | — | — | — | — | — |')
    lines += ['', '[All fits, samples, native-unit slopes and pointwise 95% intervals](trade_food_tests.csv) · '
        '[Fixed plan](../../../monitoring/trade_plan.json) · [Food basket membership](food_members.csv)', '',
        'Pointwise slope intervals are not simultaneous. Passing fits are exploratory candidates, not independently replicated discoveries.', '',
        '## Exclusions','', '| Country | Estimable / planned fits | Exclusion reasons |','|---|---:|---|']
    for country in trade_analysis.COUNTRIES:
        group=fits[fits.country.eq(country)];reasons='; '.join(sorted(set(group.loc[group.status.ne('eligible'),'reason']))) or 'None'
        lines.append(f'| {country} | {int(group.status.eq("eligible").sum())} / {len(group)} | {reasons} |')
    (output/'trade_report.md').write_text('\n'.join(lines)+'\n')
    manifest={'schema_version':1,'as_of':stamp.isoformat(),'plan_sha256':file_digest(trade_analysis.PLAN_PATH),
        'observation_fingerprint':_fingerprint(observations),'source_manifests':{name:{'sha256':file_digest(Path(root)/'manifest.json'),'snapshot_id':source['snapshot_id']}
            for name,root,source in [('shipping',shipping_root,shipping_source),('economic',economic_root,economic_source),('climate',climate_root,climate_source)]},
        'planned_fits':len(fits),'eligible_fits':len(eligible),'passing_fits':len(passing),'passing_cells':int(passing.pair_id.nunique()),
        'interpretation':fits.attrs['interpretation'],
        'outputs':{name:{'sha256':file_digest(output/name),'rows':len(frame)} for name,frame in tables.items()},
        'report_sha256':file_digest(output/'trade_report.md')}
    write_json_if_changed(output/'trade_manifest.json',manifest)
    return manifest


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,default=BASE/'results/monitoring/trade');parser.add_argument('--as-of')
    args=parser.parse_args();print(json.dumps(run(load_observations(),args.out,as_of=args.as_of),indent=2))

if __name__=='__main__':main()
