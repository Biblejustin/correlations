# Methodology

These analyses are historical exploration and prospective observation monitors. Biblical themes are interpretation metadata, not statistical target labels. Nonsignificance does not establish independence; association does not establish causation or prophetic fulfillment.

## Coverage and units

`catalog_coverage.py` resolves explicit overrides, then `<source>.coverage.json`, then `data/catalog_coverage.json`. Coverage bounds are independent of event thresholds and last qualifying events. Complete-year analyses mask current partial years, declared gaps and unreleased years. Quiet observed years can be zero; missing observations cannot.

Selected-event catalogs have a declared analytical scope, not proven complete surveillance. Within that scope, zero means no listed event. High magnitude/severity thresholds can reduce underdetection; they do not prove 100% completeness across centuries. Historical mortality combines hazard, population exposure, vulnerability, source selection and protection.

Lifetime deaths, displaced people and affected populations are equally allocated over original inclusive event durations before a requested window is sliced. These are allocation proxies, not measured annual flows. Missing event totals invalidate affected yearly totals. Drought deaths and affected populations remain separate; neither measures physical drought severity.

Flood resolution selects canonical linked events with explicit source priority before either daily or annual filtering. Tsunami cause annotations are retained from linked source rows. Ambiguous multinational matches remain a limitation. Daily tests require exact dates; a month/year does not imply the fifteenth day.

Regional observations retain source/version/URL, fetch and publication dates where available, location, unit, observation interval, numerator/denominator, dimensions and provisional status. Source boundaries differ: country names and codes alone cannot establish comparable geography. UCDP Israel includes its Palestinian conflict unit, so Israel-only per-capita rates/lags are withheld; Sudan before 2012 is likewise excluded from mismatched rates. IPC projections remain distinct from current assessments. Surveillance positivity is not population prevalence. Refugee stocks, stock changes and returns remain distinct.

## Statistical families

| Analysis | Current interpretation and correction |
|---|---|
| Cross-correlation matrix | Fixed 45 pairs; regime residuals on observed overlap, dependence-aware block-null sensitivity; unavailable cells remain in planned family |
| Granger | 30 direction/type/lag tests; BH q-values; predictive lag association, no causal identification |
| Global chains | All 104 searched lag cells corrected; selected peaks also exported with uncertainty; no unadjusted peak claims |
| Annual spectra | Fitted AR(1) surrogate null, repeat maximum-frequency search; 24-indicator band and global families; 10,000 surrogates |
| Regional drought spectra | Same affected-population units and coverage rules; 9–13-year band search + eight-region family; selected data, no solar attribution |
| Regional lags | Eight fixed countries × three pairs × three lags = 72 cells; signed-log residuals, calendar-year alignment, block permutation and BH |
| Israel crops | Original 54 historical cells preserved; separate 30-test area/yield follow-up family; HAC and block sensitivity; future holdout frozen |

BH controls the reported family under its assumptions; families are documented, not silently combined into a universal “200 tests” headline. Cross-family selection and repeated exploration remain reasons to require future validation. Pointwise intervals are not simultaneous confidence bands. Block assumptions are sensitivity choices, not guarantees of complete dependence modeling.

## Detrending, timing and dependence

Regime detrending uses fixed historical breakpoints in `detection_regimes.py`. It removes a piecewise linear baseline; results remain conditional on those choices. Constant, empty or insufficiently observed overlaps produce unavailable results.

Exact earthquake and flare timestamps preserve multiple events within one year in waiting-time diagnostics. Coarse annual catalogs support annual-rate analysis, not invented exact waiting times. Aftershocks remain in the earthquake catalog; shorter intervals do not alone demonstrate accelerating independent large-earthquake hazards.

Trend confidence intervals use fitted-trend residual blocks so resampling retains the estimated trend. A shuffled zero-trend null is a hypothesis test, not a confidence interval. Serial dependence invalidates ordinary iid resampling as a general remedy. Legacy raw Pearson/binomial outputs remain screening diagnostics where retained; do not promote them to corrected confirmatory conclusions.

Spectra and wavelets require contiguous finite annual overlap. Missing years cannot be dropped and concatenated as adjacent time. AR(1) nulls approximate persistence and repeat frequency selection; isolated peaks do not identify an astronomical mechanism. Wavelet edge regions are masked; coherence values are descriptive and are not a time-resolved causal test.

## Stable composites and future validation

Global composite v2 fixes baseline 1985–2010, domain membership, equal domain weights, minimum 20 baseline years and trailing windows. M≥8 is a sensitivity control rather than an extra M≥7 vote. Missing fixed members invalidate their domains; missing domains invalidate headline score. The current flood/drought baseline cannot support any full score. Neither normalization nor a changing subset repairs this absence.

Regional synchrony uses one variable in each of four fixed domains, a 2000–2019 reference and at least ten observed baseline years. It screens predefined thresholds. Joint interpretation requires adequate overlap and a dependency-aware null; unsupported calibration remains unavailable. No unvalidated threshold supplies a prophetic fulfillment criterion.

Historical analyses reuse observations. Israel's holdout begins with previously unseen releases/year pairs defined in the feeder plans; rainfall currently stops at 2023, so merely downloading 2024 crops does not create a complete holdout observation. Keep historical prediction text and frozen model definitions unchanged when updating diagnostics. Track effect size, uncertainty, coverage, failure and future predictive error in either direction.

## Reproducibility

Pinned runtime dependencies, deterministic seeds, source SHA-256 manifests, CSV/JSON statistical outputs and retained stage logs accompany code. SQLite fingerprints hash logical rows so same-count corrections are visible. SWPC's seven-day endpoint is durably ingested and deduplicated, with a union of actual polling intervals; missing weeks remain gaps. Failed source fetches never authorize publication of a successful complete refresh.
