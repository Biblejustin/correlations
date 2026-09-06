"""Scientific/coverage invariants for the frozen local purchasing-power monitor."""
import json

import numpy as np
import pandas as pd
import pytest

from monitoring.affordability import PLAN, build_tables, markdown_report
from monitoring.feeds import frame, obs


def pair(month, value=10, market='1', commodity='Wheat', commodity_id='1', currency='AAA',
         food_unit='KG', wage_id='277', dims_extra=None, **kw):
    month = pd.Period(month, freq='M')
    unitkg = 50 if food_unit == '50 KG' else 1
    dims = dict(market_id=market, commodity=commodity, commodity_id=commodity_id,
        currency=currency, food_unit_original=food_unit, food_unit_kg=unitkg,
        food_normalized_unit='KG', food_price_type='Retail',
        wage_series_signature={'commodity_id':wage_id, 'commodity':'Wage (non-qualified labour)',
                               'unit':'DAY', 'pricetype':'Retail', 'currency':currency},
        wage_original_units=['DAY'], wage_quote_count=1, food_quote_count=1)
    dims.update(dims_extra or {})
    row = obs('ETH', month.start_time.date(), month.end_time.date(), 'staple_kg_per_daily_wage',
        value, 'kg/day_wage', 'wfp', 'https://example.org/wfp', frequency='monthly',
        numerator=value * 10, denominator=10, dimensions=dims)
    row.update(kw)
    return row


def baseline(value=10, **kw):
    return [pair(str(m), value, **kw) for m in pd.period_range('2015-01', '2019-12', freq='M')]


def build(rows, as_of='2024-03-15'):
    return build_tables(frame(rows), as_of, PLAN)


def test_exact_month_and_year_comparators_do_not_bridge_gaps():
    result = build([pair('2023-02', 10), pair('2023-12', 12), pair('2024-02', 15)])['monthly'].set_index('month')
    assert result.loc['2024-02', 'yoy_pct'] == 50
    assert pd.isna(result.loc['2024-02', 'mom_pct'])
    assert result.loc['2024-02', 'mom_status'] == 'exact comparator unavailable'
    assert pd.isna(result.loc['2023-12', 'yoy_pct'])


@pytest.mark.parametrize('identity_change', [{'currency':'BBB'}, {'food_unit':'50 KG'}, {'wage_id':'278'}, {'market':'2'}, {'commodity':'Rice', 'commodity_id':'2'}])
def test_identity_changes_never_splice_comparators(identity_change):
    result = build([pair('2024-01', 10), pair('2024-02', 20, **identity_change)])
    assert len(result['monthly'].series_id.unique()) == 2
    assert result['monthly'].mom_pct.isna().all()


def test_quote_counts_and_equivalent_day_lineage_do_not_break_continuity():
    rows = [pair('2024-01', 10), pair('2024-02', 20, dims_extra={'wage_quote_count':3,
             'food_quote_count':2, 'wage_original_units':['1 DAY', 'DAY']})]
    result = build(rows)['monthly'].sort_values('month')
    assert result.series_id.nunique() == 1
    assert result.iloc[-1].mom_pct == 100


def test_partial_future_projection_bad_dates_and_bad_ratios_quarantined():
    rows = [pair('2024-01'), pair('2024-03'), pair('2025-01'),
            pair('2024-02', dims_extra={'type':'projection'}),
            pair('2024-02', dims_extra={'partial':True}),
            pair('2024-02', period_end='2024-02-20'),
            pair('2024-02', numerator=99), pair('2024-02', denominator=0),
            pair('2024-02', unit='USD'), pair('2024-02', period_start='not a date')]
    result = build(rows)
    assert len(result['monthly']) == 1
    assert result['manifest']['quarantined_rows'] == 9
    assert result['manifest']['last_complete_month'] == '2024-02'
    # Even the last calendar day is not a completed current month yet.
    assert build([pair('2024-02')], '2024-02-29')['monthly'].empty


def test_missing_legacy_pair_metadata_never_infers_wage_identity():
    row = pair('2024-01'); dims = json.loads(row['dimensions']); del dims['wage_series_signature']
    row['dimensions'] = json.dumps(dims)
    result = build([row])
    assert result['monthly'].empty
    assert 'missing exact pair metadata' in result['diagnostics'].iloc[0].reason


def test_identical_duplicates_collapse_but_conflicting_duplicates_remove_whole_month():
    rows = [pair('2024-01'), pair('2024-01', fetched_at='2024-03-01'),
            pair('2024-02', 10), pair('2024-02', 20)]
    result = build(rows)
    assert len(result['monthly']) == 1
    assert result['monthly'].iloc[0].duplicate_observation_count == 2
    assert result['manifest']['quarantined_rows'] == 2
    assert result['diagnostics'].reason.str.contains('conflicting duplicate').all()


def test_baseline_requires_total_and_each_year_coverage():
    rows = [pair(str(m)) for m in pd.period_range('2015-01', '2017-12', freq='M')]
    # 36 months in three years fails coverage in 2018 and 2019.
    result = build(rows)
    assert not result['basket_members'].eligible.any()
    assert result['basket_monthly'].empty
    # 36 total and >=6 in each baseline year passes.
    rows = baseline()[:12] + [r for r in baseline()[12:] if int(r['period_start'][5:7]) <= 6]
    result = build(rows)
    assert result['basket_members'].iloc[0].baseline_months == 36
    assert result['basket_members'].iloc[0].eligible


def test_fixed_equal_market_equal_staple_geometric_index_and_full_coverage():
    rows = baseline(market='A', value=10) + baseline(market='A', commodity='Rice', commodity_id='2', value=100) + baseline(market='B', value=20)
    rows += [pair('2024-01', 20, market='A'), pair('2024-01', 100, market='A', commodity='Rice', commodity_id='2'), pair('2024-01', 40, market='B')]
    rows += [pair('2024-02', 40, market='A'), pair('2024-02', 200, market='A', commodity='Rice', commodity_id='2')]
    result = build(rows)
    members = result['basket_members']
    assert sorted(members.weight) == [.25, .25, .5]
    basket = result['basket_monthly'].set_index('month')
    assert basket.loc['2024-01', 'index'] == pytest.approx(100 * 2 ** .75)
    assert basket.loc['2024-02', 'observed_members'] == 2
    assert basket.loc['2024-02', 'member_coverage'] == pytest.approx(2 / 3)
    assert pd.isna(basket.loc['2024-02', 'index'])
    # A missing current member cannot be replaced by some new market/staple.
    added = rows + [pair('2024-02', 1000, market='NEW')]
    assert build(added)['manifest']['membership_sha256'] == result['manifest']['membership_sha256']
    assert pd.isna(build(added)['basket_monthly'].set_index('month').loc['2024-02', 'index'])


def test_geometric_baseline_and_membership_do_not_depend_on_later_values():
    rows = baseline(); rows[0] = pair('2015-01', 1000)
    rows.append(pair('2024-01', 20))
    result = build(rows)
    expected = np.exp((59 * np.log(10) + np.log(1000)) / 60)
    assert result['basket_members'].iloc[0].baseline_geometric_mean == pytest.approx(expected)
    assert result['monthly'].set_index('month').loc['2024-01', 'index_2015_2019'] == pytest.approx(2000 / expected)
    rows[-1] = pair('2024-01', 10000)
    assert build(rows)['manifest']['membership_sha256'] == result['manifest']['membership_sha256']


def test_multiple_baseline_eligible_identities_same_market_staple_are_excluded():
    result = build(baseline() + baseline(currency='BBB'))
    assert len(result['basket_members']) == 2
    assert not result['basket_members'].eligible.any()
    assert result['basket_members'].eligibility_reason.str.startswith('multiple').all()
    assert not result['monthly'].empty


def test_annual_geometric_levels_require_all_twelve_months_and_exact_prior_year():
    rows = baseline() + [pair(str(m), 20) for m in pd.period_range('2020-01', '2020-12', freq='M')]
    rows += [pair('2021-01', 100), pair('2021-12', 100)]
    result = build(rows, '2022-02-01')
    annual = result['series_annual'].set_index('year')
    assert annual.loc[2020, 'value'] == pytest.approx(20)
    assert annual.loc[2020, 'yoy_pct'] == pytest.approx(100)
    assert annual.loc[2021, 'observed_months'] == 2
    assert pd.isna(annual.loc[2021, 'value'])
    basket = result['basket_annual'].set_index('year')
    assert basket.loc[2020, 'value'] == pytest.approx(200)
    assert pd.isna(basket.loc[2021, 'value'])


def test_no_data_retains_country_coverage_and_report_explains_unavailable():
    result = build([])
    assert len(result['coverage']) == 8
    assert result['coverage'].eligible_fixed_members.eq(0).all()
    text = markdown_report(frame([]), '2024-03-15')
    assert 'No eligible fixed basket' in text
    assert 'not national wages or CPI' in text
    assert '100% fixed-member coverage' in text


def test_report_selection_alphabetical_not_largest_value_and_retains_units():
    rows = [pair('2024-01', 999, market='Z'), pair('2024-01', 10, market='A')]
    text = markdown_report(frame(rows), '2024-02-01')
    assert 'A / Wheat (AAA; KG)' in text
    assert 'Z / Wheat' not in text
    assert '10.00' in text
    assert '999.00' not in text


def test_frozen_plan_changes_rejected_and_checked_against_committed_json():
    from pathlib import Path
    committed = json.loads((Path(__file__).parents[1] / 'monitoring/extension_plan.json').read_text())
    for key, value in PLAN.items(): assert committed['affordability'][key] == value
    with pytest.raises(ValueError, match='frozen design'):
        build_tables(frame([]), '2024-02-01', dict(PLAN, required_fixed_basket_coverage=.8))


def test_default_runtime_rejects_committed_numerical_plan_drift(tmp_path, monkeypatch):
    import monitoring.affordability as module
    committed = json.loads(module.PLAN_PATH.read_text())
    committed['affordability']['minimum_baseline_months'] = 24
    altered = tmp_path / 'extension_plan.json'
    altered.write_text(json.dumps(committed))
    monkeypatch.setattr(module, 'PLAN_PATH', altered)
    with pytest.raises(ValueError, match='Committed affordability plan differs.*minimum_baseline_months'):
        module.build_tables(frame([]), '2024-02-01')
