# Research backlog

September 2026 integrity work and first regional monitoring panel implemented. Earlier claims are superseded by regenerated results and [methodology](METHODOLOGY.md).

| Work | Status |
|---|---|
| Explicit coverage; duration allocation; flood canonical events | Implemented, tested; unresolved flood linkage remains |
| Actual event waiting times; finite wavelet overlap | Implemented, tested |
| Granger/lag-search correction; red-noise spectral sensitivity | Implemented; historical exploratory results |
| Stable domain weights, baseline and trailing windows | Implemented; global composite unavailable with present impact coverage |
| Same-count revisions, flare ingestion, feeder synchronization, failure-aware refresh | Implemented with source and artifact manifests |
| USGS withdrawals and corrections | Implemented with verified counts, complete half-open query scopes, atomic reconciliation and 30-day historical cache expiry |
| Shared Make entrypoints, clean dependencies and CI | Implemented; exact dependency/import verification, fixture failure checks and read-only GitHub CI |
| Wheat area/yield and irrigation covariates | Implemented; future holdout frozen; 17-year irrigation sample limited |
| Regional UCDP, UNHCR, IPC, WFP affordability | Implemented for fixed eight-country pilot; stock changes are not new displacement flows |
| IPC national assessment history and revisions | Full supplied history ingested; 384 pilot observations, six ambiguous/inconsistent periods quarantined with original rows, prior versions preserved; geographic gates unchanged |
| IDMC annual displacement flows and stocks | Implemented through 2025, separate movements/people units; no added cross-source lag claims |
| Current Israel national rain, heat, PET and wet days | Separate CRU-CY4.10 monitor through 2025; full overlap diagnostics and five-coefficient heat/irrigation sensitivity; original model frozen |
| WHO respiratory positivity, religious freedom, Kinneret | Implemented with scope and coverage labels |

## Observations to improve next

1. **Comparable IPC geography and displacement definitions.** Full national IPC history is now ingested from the public HDX historical resource, with exact-period assessed-population denominators and versioned prior snapshots. The pilot has only 2021-onward coverage, and the export lacks publisher assessment IDs and boundary geometry; five ambiguous periods and one inconsistent phase partition remain quarantined. Verify stable territory and population-group definitions before using subnational exports or unlocking country lag tests. IDMC movements are available; verify cause definitions and matched geography before extending tests. Annual and separate disaster-event exports must not be added without compatible definitions.
2. **Israel water attribution and future validation.** CRU-CY4.10 now supplies current national rain/heat/PET through 2025. Its aggregation is not interchangeable with frozen CCKP4.08 input. Verify crop-relevant geography and product continuity; add measured soil moisture, aquifer storage, desalination, reclaimed water and wheat-specific irrigation where supported. At least ten compatible future crop/rain pairs are still required; no prospective success has been scored.
3. **Hazard and vulnerability.** Replace sparse impact proxies with measured drought/rain/heat, flood exposure, cyclone wind/rain and earthquake shaking. Add population exposed, warning capacity and building vulnerability before interpreting death trends as hazard trends.
4. **Seasonal disease burden.** Extend beyond influenza positivity where tested denominators, severe admissions or excess-mortality series are comparable. Reporting-site changes and disease seasonality require explicit baselines; annual averages are provisional diagnostics.
5. **Restrictions and contemporary incidents.** V-Dem religious freedom is a broad annual index. Add documented arrests, worship restrictions and religion-related violence with reproducible inclusion rules, evidence links and denominators. No automatic political-event selection.
6. **Trade and climate pathways.** PortWatch maritime disruption, staple import dependence, exchange rates, ENSO/RONI and IOD could test regional mechanisms. Predeclare geography/lags and compare predictive performance beyond existing variables.
7. **Complete celestial denominator.** Extend `tetrad-check` with predefined locations/calendar rules, visibility, altitude and totality duration. Famous selected events cannot establish rarity.
8. **Prospective validation and calibrated synchrony.** Gather sufficient complete domain overlap. Freeze future hypotheses before data releases; report prediction error and failures. More categories or shorter eligibility requirements are not substitutes for missing coverage.

## Source integrity limits

USGS query-cache migration intentionally refetches histories without verifiable query metadata. Complete, independently counted query windows now reconcile withdrawn, revised and reclassified events inside that exact scope; incomplete queries cannot remove records. Failed NOAA refreshes retain old snapshots and return a degraded/error status. Old curated catalogs do not become complete through the current year merely because a fetch job ran. Flood linkage diagnostics identify review candidates; structural conflicts need source-by-source adjudication. No complete modern flood-mortality estimate is available under the current strict unknown-total rule.
