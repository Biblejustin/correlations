# Trade, currencies and food-price monitoring

Reference cutoff: 2026-09-06T00:26:20.198155-05:00 (America/Chicago).

192 frozen comparisons; 6 estimable fits; 0 pass BH q < 0.05, covering 0 distinct country/predictor/lag cells. Two fits of one cell are related sensitivities.

Historical exploratory associations support observation, not causal or prophetic-fulfillment claims. Sources can revise; these snapshots do not reconstruct what was known in each historical month.

## Shipping observations

| Chokepoint | Latest eligible month | Mean estimated transit, metric tons/day | YoY decline |
|---|---|---:|---:|
| Suez Canal | 2026-07 | 1,599,606 | -15.4% |
| Bab el-Mandeb | 2026-07 | 1,297,706 | -15.0% |
| Strait of Hormuz | 2026-07 | 373,463 | +89.7% |

PortWatch estimates payload-weighted vessel transit from AIS, across all vessel classes. They do not measure grain cargo or a country’s imports. Suez and Bab el-Mandeb often describe the same route. Every calendar day is required; seven elapsed days after month end are excluded by this project. This delay does not make preliminary IMF estimates final. Missing source days remain missing.

[IMF PortWatch daily source](https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/Daily_Chokepoints_Data/FeatureServer/0) · [Source manifest](../../../data/trade_shipping/manifest.json) · [All monthly coverage](shipping_monthly.csv)

## Currency and cereal-import context

| Country | Latest official FX month / YoY | Latest cereal-dependence window / ratio | Fixed food-series currencies |
|---|---|---|---|
| ISR | 2026-03 / -14.8% | 2021–2023 / 93.7% (flag E) | No eligible basket |
| PSE | Unavailable | Unavailable | ILS; incompatible with official FX |
| LBN | 2026-03 / +0.0% | 2021–2023 / 86.6% (flag E) | LBP |
| UKR | 2026-03 / +5.7% | 2021–2023 / -298.4% (flag E) | UAH |
| SDN | 2024-10 / +2.0% | Unavailable | SDG |
| ETH | 2026-03 / +20.9% | 2021–2023 / 8.6% (flag E) | ETB |
| SOM | 2018-06 / +1.4% | Unavailable | SLS;SOS; incompatible with official FX |
| YEM | 2026-03 / -3.2% | 2021–2023 / 93.4% (flag E) | YER |

Positive FX change means official local-currency depreciation against USD. Official rates may differ materially from retail or parallel-market rates. Only explicitly monthly World Bank GEM DPANUSLCU observations are used. A food basket must use one verified matching currency; missing countries, months and incompatible baskets stay unavailable.

FAOSTAT cereal dependence remains a full three-year average: 100 × (imports − exports) / (production + imports − exports). Negative values indicate net exports. It supplies descriptive context, never a monthly predictor or grain-shipment estimate. All periods and source flags remain in the source archive.

[World Bank GEM source](https://api.worldbank.org/v2/indicator/DPANUSLCU?format=json) · [FAOSTAT food-security source](https://www.fao.org/faostat/en/#data/FS) · [Versioned economic sources](../../../data/economic_sources/manifest.json)

## Fixed comparison family

Eight countries × four predictors × lags 0, 1 and 3 months × two fits = 192 tests. Positive lag pairs an earlier predictor month with a later food-price response. Both fits use the same longest contiguous complete span, at least 60 months and eight residual degrees of freedom. Missing tests remain in BH as p = 1.

Food response is the country median of exact-series log year-on-year retail changes. Membership requires at least 24 observed months in 2015–2019; each month requires at least three series and 70% of fixed membership. This monitored-market basket is not CPI. Baseline controls include trend and calendar-month indicators. Adjustment adds RNI, DMI and applicable official FX controls in predictor and response months. HAC uses 12 Bartlett lags, finite-sample correction and Student-t inference. Overlapping YoY windows and common crisis shocks limit inference.

| Country | Predictor | Lag months | Fit | Sample | Partial r | BH q |
|---|---|---:|---|---|---:|---:|
| All countries | No fit passes | — | — | — | — | — |

[All fits, samples, native-unit slopes and pointwise 95% intervals](trade_food_tests.csv) · [Fixed plan](../../../monitoring/trade_plan.json) · [Food basket membership](food_members.csv)

Pointwise slope intervals are not simultaneous. Passing fits are exploratory candidates, not independently replicated discoveries.

## Exclusions

| Country | Estimable / planned fits | Exclusion reasons |
|---|---:|---|
| ISR | 0 / 24 | no_verified_single_currency_food_basket |
| PSE | 0 / 24 | no_verified_single_currency_food_basket |
| LBN | 0 / 24 | insufficient_contiguous_months |
| UKR | 0 / 24 | insufficient_contiguous_months |
| SDN | 0 / 24 | insufficient_contiguous_months |
| ETH | 0 / 24 | insufficient_contiguous_months |
| SOM | 0 / 24 | no_verified_single_currency_food_basket |
| YEM | 6 / 24 | insufficient_contiguous_months |
