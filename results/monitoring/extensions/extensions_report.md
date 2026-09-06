# Climate, respiratory and purchasing-power monitors

Reference date: 2026-09-06 (America/Chicago). Exact cutoff: 2026-09-06T08:19:14.820420-05:00.

Historical exploratory extensions. Source revisions are retained; reference dates do not reconstruct release-time availability. These measures support observation and comparison, not prophetic-fulfillment claims.

## Ocean climate observations

| Index | Latest complete observation window | Value, °C anomaly | Product |
|---|---|---:|---|
| RNI | 2026-08-01–2026-08-31 | +1.67 | Relative ERSSTv6; 1991-2020 baseline |
| DMI | 2026-05-01–2026-05-31 | +0.15 | HadISST1.1; NOAA PSL Dipole Mode Index |
| RONI | 2026-06-01–2026-08-31 | +1.36 | Relative ERSSTv6; 1991-2020 baseline; three-month running mean |

Paired complete calendar years: 1950–2025 (76 years). Monthly RNI supplies the annual ENSO control; seasonal RONI spans its full three-month window. DMI measures the Indian Ocean west-minus-east sea-surface-temperature gradient. CPC values may revise; DMI is preliminary. No partial annual values or inferred local rainfall.

[NOAA CPC definitions](https://www.cpc.ncep.noaa.gov/data/indices/) · [NOAA PSL DMI definition](https://psl.noaa.gov/data/timeseries/month/DMI/) · [Versioned source manifest](../../../data/climate_indices/manifest.json)

## Climate-control sensitivity

Historical climate-control sensitivity uses paired samples and fixed hypotheses.
Baseline fits remove shared time/regime terms; adjusted fits also remove annual monthly-RNI and DMI terms.
Seasonal RONI is a separate monitor and is not used in these calendar-year fits.
Global: 90 planned tests across both fits; 72 eligible, 0 BH q<0.05.
Unavailable: insufficient_contiguous_years=18.
Regional: 144 planned tests across both fits; 34 eligible, 2 BH q<0.05.
Unavailable: insufficient_contiguous_years=108; insufficient_residual_degrees_of_freedom=2.
BH families are separate for the pre-existing global and regional panels; unavailable tests remain in each family.
Slope confidence intervals are pointwise. Climate adjustment does not establish causation, forecasting skill, or prophetic significance.

| Family / country | Predictor → response | Lag | Fit | Years | Partial r | BH q |
|---|---|---:|---|---|---:|---:|
| regional / UKR | conflict_total_deaths_per_100k → refugees_origin_stock_change | 0 | baseline_time_regime | 2001–2025 | +0.593 | 0.0048 |
| regional / UKR | conflict_total_deaths_per_100k → refugees_origin_stock_change | 0 | climate_adjusted | 2001–2025 | +0.590 | 0.0048 |

Table lists all passing fits; [all 90 global fits](global_climate_sensitivity.csv) and [all 144 regional fits](regional_climate_sensitivity.csv) preserve every planned result and unavailable cell. A change after adjustment does not establish mediation or causation. These HAC sensitivities do not replace the original block-null tests.

2 passing fits describe 1 distinct country/pair/lag associations. Two fits for one association are sensitivity comparisons, not independent discoveries. Refugee-origin stock change is a net stock difference, not newly displaced people.

## Seasonal sentinel influenza

| Country / stream | Expected ISO week | Tested | Positivity | Seasonal baseline | Difference | Status |
|---|---|---:|---:|---:|---:|---|
| ETH / 53b5453d | 2026-W34 | 104 | 2.9% | 6.4% | -3.5 pp | available; provisional |
| ISR / 3007b668 | 2026-W34 | — | — | — | — | unobserved week |
| LBN / 3c1f8d84 | 2026-W34 | — | — | — | — | unobserved week |
| PSE / 877a128d | 2026-W34 | — | — | — | — | unobserved week |
| SDN / ed1c35a0 | 2026-W34 | — | — | — | — | unobserved week |
| SOM / 4a810eaf | 2026-W34 | — | — | — | — | unobserved week |
| UKR / f2db5a97 | 2026-W34 | 30 | — | — | — | low testing; provisional |
| YEM / 96269d5e | 2026-W34 | — | — | — | — | unobserved week |

References use only prior ISO years, with minimum specimen/week and historical-window coverage rules. Latest expected weeks remain visible when data are missing. Reporting-site coverage is unverified; these are descriptive positivity differences, not outbreak diagnoses or calibrated p-values.

[Weekly differences and eligibility](seasonal_flu_weekly.csv) · [Historical seasonal windows](seasonal_flu_baseline_windows.csv) · [WHO source](https://xmart-api-public.who.int/FLUMART/VIW_FNT)

## Food purchasing power

Food purchasing power uses exact matched WFP retail staple / non-qualified daily-wage series. MoM and YoY require exact calendar comparators. Completed months only; missing comparisons stay unavailable. Values describe monitored markets, not national wages or CPI.

| Country | Market / staple (currency; quoted food unit) | Month | Kg per daily wage | MoM | YoY |
|---|---|---|---:|---:|---:|
| ETH | 1831 / Maize (white) (ETB; 100 KG) | 2015-08 | 10.77 | unavailable | unavailable |
| ISR | No validated exact pairs | — | unavailable | unavailable | unavailable |
| LBN | No validated exact pairs | — | unavailable | unavailable | unavailable |
| PSE | No validated exact pairs | — | unavailable | unavailable | unavailable |
| SDN | No validated exact pairs | — | unavailable | unavailable | unavailable |
| SOM | No validated exact pairs | — | unavailable | unavailable | unavailable |
| UKR | No validated exact pairs | — | unavailable | unavailable | unavailable |
| YEM | 192 / Rice (imported) (YER; KG) | 2026-07 | 8.80 | +5.9% | -5.6% |

Examples are nonrepresentative: alphabetical first market/staple among each country’s latest complete observations. Full tables preserve wage identity, prices, source timestamps, missing comparators and staleness.

Fixed monitored-market purchasing-power index: each baseline-eligible exact series equals 100 at its 2015–19 geometric mean. Equal market weights, equal fixed-staple weights within each market; every index requires 100% fixed-member coverage. Annual values require 12 complete months. No seasonal adjustment.

| Country | Latest available index month | Index | MoM | YoY | Latest completed-month member coverage |
|---|---|---:|---:|---:|---:|
| ETH | No eligible fixed basket | unavailable | unavailable | unavailable | 0 members |
| ISR | No eligible fixed basket | unavailable | unavailable | unavailable | 0 members |
| LBN | No eligible fixed basket | unavailable | unavailable | unavailable | 0 members |
| PSE | No eligible fixed basket | unavailable | unavailable | unavailable | 0 members |
| SDN | No eligible fixed basket | unavailable | unavailable | unavailable | 0 members |
| SOM | No eligible fixed basket | unavailable | unavailable | unavailable | 0 members |
| UKR | No eligible fixed basket | unavailable | unavailable | unavailable | 0 members |
| YEM | No eligible fixed basket | unavailable | unavailable | unavailable | 0 members |

ETH basket unavailable: at most 1 baseline months per exact series; baseline years with no matched pairs: 2016, 2017, 2018, 2019. Required: 36 months total and at least 6 in every year from 2015 through 2019.

YEM basket unavailable: at most 43 baseline months per exact series; baseline years with no matched pairs: 2015. Required: 36 months total and at least 6 in every year from 2015 through 2019.

Validation excluded 0 rows; exact reasons and baseline eligibility remain in diagnostics. Historical revised snapshots are exploratory; reference-period cutoffs do not reconstruct information available at release time.

[Exact monthly series](affordability_monthly.csv) · [Fixed basket membership](affordability_basket_members.csv) · [Monthly indices](affordability_basket_monthly.csv) · [Coverage](affordability_coverage.csv)

Definitions and frozen comparison rules: [extension plan](../../../monitoring/extension_plan.json) and [monitoring documentation](../../../MONITORING.md).
