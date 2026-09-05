# Research backlog

September 2026 integrity work and first regional monitoring panel implemented. Earlier claims are superseded by regenerated results and [methodology](METHODOLOGY.md).

| Work | Status |
|---|---|
| Explicit coverage; duration allocation; flood canonical events | Implemented, tested; unresolved flood linkage remains |
| Actual event waiting times; finite wavelet overlap | Implemented, tested |
| Granger/lag-search correction; red-noise spectral sensitivity | Implemented; historical exploratory results |
| Stable domain weights, baseline and trailing windows | Implemented; global composite unavailable with present impact coverage |
| Same-count revisions, flare ingestion, feeder synchronization, failure-aware refresh | Implemented with source and artifact manifests |
| Wheat area/yield and irrigation covariates | Implemented; future holdout frozen; 17-year irrigation sample limited |
| Regional UCDP, UNHCR, IPC, WFP affordability | Implemented for fixed eight-country pilot; stock changes are not new displacement flows |
| WHO respiratory positivity, religious freedom, Kinneret | Implemented with scope and coverage labels |

## Observations to improve next

1. **Longer comparable IPC history and displacement flows.** Public IPC export is latest-assessment oriented. Accumulate versioned snapshots and preserve assessed territory/population. Add separately documented new-displacement flows; do not substitute stock differences.
2. **Current Israel rain and water balance.** Historical CRU TS4.08 stops in 2023. Add verified IMS stations or fixed-area CHIRPS v3 with validation across overlap; do not silently splice products. Aquifer storage, desalination and reclaimed-water observations remain separate missing inputs. Crop-specific irrigation and soil/temperature controls would improve attribution.
3. **Hazard and vulnerability.** Replace sparse impact proxies with measured drought/rain/heat, flood exposure, cyclone wind/rain and earthquake shaking. Add population exposed, warning capacity and building vulnerability before interpreting death trends as hazard trends.
4. **Seasonal disease burden.** Extend beyond influenza positivity where tested denominators, severe admissions or excess-mortality series are comparable. Reporting-site changes and disease seasonality require explicit baselines; annual averages are provisional diagnostics.
5. **Restrictions and contemporary incidents.** V-Dem religious freedom is a broad annual index. Add documented arrests, worship restrictions and religion-related violence with reproducible inclusion rules, evidence links and denominators. No automatic political-event selection.
6. **Trade and climate pathways.** PortWatch maritime disruption, staple import dependence, exchange rates, ENSO/RONI and IOD could test regional mechanisms. Predeclare geography/lags and compare predictive performance beyond existing variables.
7. **Complete celestial denominator.** Extend `tetrad-check` with predefined locations/calendar rules, visibility, altitude and totality duration. Famous selected events cannot establish rarity.
8. **Prospective validation and calibrated synchrony.** Gather sufficient complete domain overlap. Freeze future hypotheses before data releases; report prediction error and failures. More categories or shorter eligibility requirements are not substitutes for missing coverage.

## Source integrity limits

USGS query-cache migration intentionally refetches histories without verifiable query metadata. Withdrawal reconciliation is still open. Failed NOAA refreshes retain old snapshots and return a degraded/error status. Old curated catalogs do not become complete through the current year merely because a fetch job ran. No complete modern flood-mortality estimate is available under the current strict unknown-total rule.
