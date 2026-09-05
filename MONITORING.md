# Monitoring definitions

Fixed exploratory pilot: Israel (ISR), Palestinian territories (PSE), Lebanon, Ukraine, Sudan, Ethiopia, Somalia and Yemen. This deliberately chosen pilot is not a representative world sample. Source territory labels remain authoritative: a shared country code does not make different footprints interchangeable.

Configuration is versioned in `monitoring/config.json`. Normalized observations retain country, observation start/end, metric, value, unit, numerator/denominator, frequency, source ID/version/URL, available publication date, retrieval date, provisional status, source dimensions and quality note. Missing publication dates remain missing. Manifests retain request hashes and observation/projection bounds. Source CSVs are individual release snapshots; retrieved IPC assessments accumulate locally by assessment identity.

## Active sources

| Source | Measures | Frequency / coverage limitation |
|---|---|---|
| [UCDP v26.1](https://ucdp.uu.se/downloads/) organized violence country-year | Best-estimate state/nonstate/civilian-targeting and total deaths; deaths per 100,000 with WDI | Annual through 2025. Seven pilot countries present; no invented PSE zero. UCDP Israel includes its Palestinian conflict unit: the source total is labeled and excluded from Israel-only population rates/lags. Sudan before 2012 lacks a matched population boundary. These measured deaths replace intensity-band floor estimates in the new panel. |
| [UNHCR population API](https://api.unhcr.org/population/v1/) | Refugees/asylum seekers by origin; refugee returns | Annual. Stocks are summed by reported origin aggregate; returns are flows. Stock difference is net change, not newly displaced population. |
| [IPC public HDX export](https://data.humdata.org/dataset/global-acute-food-insecurity-country-data) | Phase 3+/3/4/5 shares, affected and analyzed populations | Assessment periods. Numerator/denominator use assessed population; country total retained separately. Current vs projection preserved; expired current assessments clearly labeled. Cross-source country lags require verified matching assessment footprint. Latest export cannot supply invented historical assessments. |
| [WFP food prices on HDX](https://data.humdata.org/organization/wfp) | Retail wheat/barley/maize/rice/sorghum/oil prices; non-qualified daily labor wages; matched kg per daily wage | Monthly market/commodity/unit/currency streams. Wage quotes and milling services are distinct from food prices. No conversion or affordability estimate without matching wage and staple observations. |
| [WHO FluNet](https://www.who.int/teams/global-influenza-programme/surveillance-and-monitoring/influenza-surveillance-outputs) / [public FluMart API](https://xmart-api-public.who.int/FLUMART/VIW_FNT) | Influenza positivity with tested-specimen denominator; source surveillance stream | Weekly, provisional. Minimum 20 processed specimens per row. Sentinel annual diagnostics need 26 reported weeks. Neither population prevalence nor all-cause disease burden. |
| [V-Dem v16](https://www.v-dem.net/data/the-v-dem-dataset/) | Religious freedom `v2clrelig`, with uncertainty columns | Annual expert-coded index. PSE source refers to West Bank; excluded from combined-territory annual panel. Higher freedom is not an incident count or persecution rate. |
| [World Bank population](https://data.worldbank.org/indicator/SP.POP.TOTL) | Same-year population denominator | Annual observed releases; geographic comparability still needs checking. |
| [Israel crop/water feeder](https://github.com/Biblejustin/israel-rain-agriculture) | FAOSTAT crop production/area/yield, crop flags; WDI irrigation/freshwater; official Kinneret | Historical CRU TS4.08 rain through 2023; annual crop release; irregular irrigation/freshwater observations; daily lake level where reported. No interpolation across missing water/covariate years. |
| [NOAA SWPC](https://services.swpc.noaa.gov/json/goes/primary/xray-flares-7-day.json) | Recent flare event ID, peak timestamp/class, satellite | Rolling seven-day observations. Durable deduplication and revisions; missed polling intervals remain gaps. Historical curated X-flare list remains selected. |

`data/monitoring/*.manifest.json` gives the fetched source URLs and versioned request evidence. Compressed CSVs use deterministic gzip headers. Cache responses support offline replay; cached responses retain their original retrieval dates. A failed or suspiciously shrunken refresh retains the previous good snapshot and returns failure.

## Derived measures and testing

**Food affordability.** Compare retail staple mass purchasable with one same-market, same-month, same-currency daily non-qualified wage. Commodity, market, price type, currency and units are preserved. This is a local purchasing-power measure, not a numerical fulfillment threshold for Revelation 6:6.

**Food-price changes.** Compare each retail staple series with itself exactly twelve calendar months earlier. Fix series membership using at least 24 observations in 2015–2019. Monthly aggregation requires at least 70% of fixed series and at least three series; annual diagnostics require nine eligible months. The median matched-series change is not CPI or a nationally representative basket.

**Regional lag family.** Conflict deaths per 100,000 → net refugee-stock change; conflict → IPC 3+; retail staple price change → IPC 3+. Eight countries × three pairs × lags 0/1/2 years = 72 fixed tests. Positive lag means predictor earlier than response. Longest contiguous finite overlap must have at least twelve years. Signed-log measures are separately detrended; three-year block permutations provide exploratory p-values; BH keeps all 72 cells in the family. Missing IPC history or uncertain geography leaves those tests unavailable.

**Regional synchrony.** Four fixed domains: conflict, food prices, influenza sentinel positivity, religious restrictions. Baseline 2000–2019, at least ten observed baseline years; extreme threshold z > 1.5, compound screen at least two domains. Every fixed domain must be eligible. Dependence-aware calibration requires sufficient joint observations; coverage failure remains unavailable. The annual panel does not yet model disease seasonality or household exposure to several hazards.

**Israel follow-up.** Area and yield separate agricultural expansion from per-hectare response. The 54 historical crop/rain tests and 30 follow-up decomposition tests remain separate declared families. Irrigation sensitivity uses actual irregular source observations and calendar-distance HAC. Rain × era tests interaction directly. The future holdout remains frozen; no later year can validate until corresponding rain and crop observations both exist.

## Commands and cadence

```bash
python refresh_monitoring.py                    # all configured public adapters
python refresh_monitoring.py --sources ipc who  # selected sources
python refresh_monitoring.py --offline          # replay saved source responses
python sync_feeders.py                          # verified sibling snapshots, including Israel
python sync_feeders.py --check                  # detect drift; no writes
python monitor_regional.py                      # panel, lag family, synchrony and report
```

A weekly full refresh is suitable for operational polling; annual feeds will often be unchanged. SWPC's seven-day retention requires polls no more than seven days apart to avoid gaps. Kinneret and WHO can be refreshed more frequently; annual inferential analyses still exclude partial years. `weekly_update.sh` integrates these steps but does not install a new scheduler. Existing scheduled callers should choose `--publish` explicitly if automatic Git publication is desired.

Outputs: `results/monitoring/monitoring_report.md`, `regional_annual_panel.csv`, `regional_lag_tests.csv` and `regional_synchrony.csv`; source observations remain available for narrower review.

## Biblical theme metadata

Food affordability/harvest echoes [Revelation 6:6](https://www.biblegateway.com/passage/?search=Revelation+6%3A6&version=KJV) and [Deuteronomy 11:14](https://www.biblegateway.com/passage/?search=Deuteronomy+11%3A14&version=KJV); conflict and flight, [Matthew 24:6–7,16](https://www.biblegateway.com/passage/?search=Matthew+24%3A6-7%2C16&version=KJV); disease and celestial observations, [Luke 21:11,25](https://www.biblegateway.com/passage/?search=Luke+21%3A11%2C25&version=KJV); religious restrictions, [Matthew 24:9](https://www.biblegateway.com/passage/?search=Matthew+24%3A9&version=KJV). These associations guide watchful questions. Statistical evidence cannot establish fulfillment, divine intent or a timetable.
