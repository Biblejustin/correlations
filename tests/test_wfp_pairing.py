"""Pairing regressions: raw wages survive; derived ratios keep exact signatures."""
import json

import pandas as pd
import pytest

from monitoring.feeds import normalize_wfp, validate_observations

COLUMNS = ['date','market_id','commodity','commodity_id','unit','priceflag','pricetype','currency','price']


def quote(commodity='Wheat', commodity_id=1, unit='KG', price=10, **kw):
    row = dict(zip(COLUMNS, ['2024-01-15', 7, commodity, commodity_id, unit, 'actual', 'Retail', 'AAA', price]))
    row.update(kw)
    return row


def wage(**kw):
    return quote('Wage (non-qualified labour)', 277, 'DAY', 100, **kw)


def normalized(rows):
    return normalize_wfp(pd.DataFrame(rows), 'ETH', 'https://example.org/wfp.csv')


def ratios(rows):
    output = normalized(rows)
    validate_observations(output)
    return output[output.metric.eq('staple_kg_per_daily_wage')]


@pytest.mark.parametrize('change', [{'commodity_id': 278}, {'commodity': 'Wage (non-qualified labour, male)'}, {'pricetype': 'Wholesale'}])
def test_distinct_wage_signature_withholds_ratio_and_preserves_raw(change):
    other = wage(); other.update(change)
    output = normalized([wage(), other, quote()])
    assert output.metric.eq('labor_wage').sum() == 2
    assert not output.metric.eq('staple_kg_per_daily_wage').any()
    dims = output[output.metric.eq('labor_wage')].dimensions.map(json.loads)
    assert all(x['affordability_wage_signature_count'] == 2 for x in dims)
    assert all('ambiguous' in x['affordability_pairing_status'] for x in dims)
    validate_observations(output)


def test_equivalent_day_units_and_exact_food_duplicates_use_within_series_medians():
    second = wage(); second.update(unit='1 DAY', price=300)
    food = quote(unit='50 KG', price=500)
    other = dict(food, price=1500)
    output = normalized([wage(), second, food, other])
    validate_observations(output)
    row = output[output.metric.eq('staple_kg_per_daily_wage')].iloc[0]
    dims = json.loads(row.dimensions)
    assert row.numerator == 200
    assert row.denominator == 20
    assert row.value == 10
    assert dims['food_unit_original'] == '50 KG'
    assert dims['food_unit_kg'] == 50
    assert dims['food_normalized_unit'] == 'KG'
    assert dims['wage_original_units'] == ['1 DAY', 'DAY']
    assert dims['food_quote_count'] == dims['wage_quote_count'] == 2
    assert dims['wage_series_signature'] == {'commodity_id':'277', 'commodity':'Wage (non-qualified labour)', 'unit':'DAY', 'pricetype':'Retail', 'currency':'AAA'}
    assert output.metric.eq('food_price').sum() == 2


def test_no_pairing_across_market_currency_or_unconvertible_units():
    rows = [wage(), quote(market_id=8), quote(currency='BBB'), quote(unit='bag')]
    assert ratios(rows).empty


def test_empty_wages_and_nonactual_quotes_are_not_ratios():
    assert ratios([quote()]).empty
    forecast = wage(); forecast['priceflag'] = 'forecast'
    assert ratios([quote(), forecast]).empty


def test_distinct_food_units_and_commodities_remain_separate():
    rows = [wage(), quote(), quote(unit='50 KG', price=500), quote(commodity='Rice', commodity_id=2)]
    output = ratios(rows)
    assert len(output) == 3
    assert len(set(output.dimensions)) == 3


def test_repeated_quote_lineage_preserves_original_annual_price_series_and_eligibility():
    from monitoring.analysis import food_price_changes
    single, repeated = [], []
    # Three fixed market series meet the original annual panel's coverage gate.
    # Repeated quotes span baseline and comparison years; their within-month
    # medians reproduce the same price path without discarding quote lineage.
    for market in ['A', 'B', 'C']:
        for month in pd.period_range('2017-01', '2020-12', freq='M'):
            price = 20 if month.year < 2020 else 30
            single.append(quote(market_id=market, date=f'{month}-15', price=price))
            repeated.extend([
                quote(market_id=market, date=f'{month}-10', price=price - 10),
                quote(market_id=market, date=f'{month}-20', price=price + 10),
            ])
    ordinary = normalized(single)
    duplicated = normalized(repeated)
    validate_observations(duplicated)
    original = duplicated.copy(deep=True)
    assert duplicated.dimensions.str.contains('source_quote_ordinal').all()
    assert duplicated.dimensions.str.contains('source_quote_date').all()
    expected = food_price_changes(ordinary)
    actual = food_price_changes(duplicated)
    pd.testing.assert_frame_equal(actual, expected)
    pd.testing.assert_frame_equal(duplicated, original)
    assert actual.set_index('year').loc[2020, 'value'] == pytest.approx(50)
    assert actual.set_index('year').loc[2020, 'n_observations'] == 12
