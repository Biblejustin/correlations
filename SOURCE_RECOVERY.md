# WFP and IPC source recovery

Audit date: 6 September 2026. No observations imported and no eligibility rules changed. This is a bounded source investigation, not proof that missing measurements never existed.

The [request ledger](data/source_recovery/requests.json) preserves exact URLs, retrieval times, HTTP outcomes and hashes of archived responses. [Resource inventory](data/source_recovery/resource_inventory.csv), [discovery results](data/source_recovery/discovery_results.json) and [web discovery](data/source_recovery/web_discovery.json) show what was searched. Failed requests remain unavailable; they never establish zero coverage.

## WFP purchasing-power baseline

The frozen index requires 36 matched months in 2015–2019 and at least six months in **each** year. Current Yemen non-qualified daily wages begin June 2016. Ethiopia has one qualifying wage quote, August 2015. Its separately labeled casual-labour stream begins in 2020; it cannot repair the earlier baseline. These are source limitations, not missing-value handling errors. Exact stream and annual coverage appear in [wage coverage](data/source_recovery/wage_coverage.csv) and [pair coverage](data/source_recovery/exact_pair_coverage.csv).

Both current exports reproduce the same 79 exact pair identities (77 Yemen, two Ethiopia), with zero baseline-eligible series. Every Yemen/Ethiopia quote in the five global baseline files matches a current country-export quote on date, market/commodity IDs and labels, unit, currency, price type, observation flag and value. No additional baseline quote was recovered.

The audit checks current country prices, their HDX resource inventories and the latest 100 package-activity records per country. Those activity records cover approximately October 2025–August 2026 and mainly repeat live resource URLs; they are not archived 2015 quotes. The current global dataset's five 2015–2019 year files reproduce the missing baseline wages: its 2015 file contains one Ethiopia non-qualified wage quote and none for Yemen. The audit also probes the retired global export ending August 2021. [HDX's 2018 migration account](https://centre.humdata.org/getting-up-to-speed-wfp-food-data-on-hdx/) explains why both global and country exports were investigated. Global/country differences are retained as review candidates, never automatically preferred or merged.

A [March 2015 FEWS NET bulletin](https://fews.net/sites/default/files/documents/reports/Yemen_2015_03_PB.pdf) credits WFP VAM and plots daily-labour/wheat-flour purchasing power for named Yemen markets. Earlier measurements therefore existed. The figures do not provide raw monthly quotes with the exact WFP market, commodity and wage identifiers needed to join present streams. Digitizing chart lines would not establish those identities.

The apparent longer [World Bank Yemen price series](https://microdata.worldbank.org/index.php/catalog/4508/study-description) combines measurements with machine-learning estimates of missing values and adjusted outliers. It is a separate modeled product, unsuitable as observed WFP baseline recovery.

The retired HDX global export was recovered completely after its bulk download timed out. Fifteen non-overlapping HTTP ranges cover all 225,787,557 bytes; every response had the expected byte range and one shared strong ETag and modification date. The assembled archive contains 2,050,638 rows, including 61,433 Yemen/Ethiopia rows. It confirms the same wage gap: no Yemen wages in 2015; Ethiopia's only non-qualified wage quote is August 2015. Its separately labeled qualified/casual wages do not repair that baseline. [Range receipts](data/source_recovery/legacy_range_receipts.json) and the full archive hash preserve the recovery evidence. The earlier bulk failure, filtered DataStore resource-not-found response and successful 2015-file retry remain in the ledger.

Recovery requires publisher raw quotes or a versioned archive, an authoritative old-to-current market/commodity/wage identity crosswalk, unchanged wage definition and exact food units/currency, and reconciliation of overlapping quoted values. Source version differences must be retained. Adding current months cannot fill a missing frozen baseline year.

## IPC assessment identities and geography

The [schema audit](data/source_recovery/ipc_schema_audit.json) examines 5,607 national, 42,707 level-1 and 377,762 area rows from full HDX histories. None includes assessment/area identifier or geometry columns. Pilot coverage still begins in 2021 or later; the larger files do not supply comparable earlier pilot observations. Their area names and assessment-month labels do not establish stable assessment IDs, boundary versions, disjoint population groups or geographic comparability. Existing quarantined periods remain excluded. Scope names alone cannot resolve Ethiopia's conflicting 2021 assessments, Somalia's conflicting 2026 assessments, or Sudan's inconsistent phase-count partition.

An authoritative recovery route exists in the [IPC API documentation](https://www.ipcinfo.org/ipc-country-analysis/api/). IPC provides detailed population tables and geographic outputs after approving access. Its [public technical schema](https://docs.api.ipcinfo.org/api/public/openapi.json) supplies analysis `id`, area `id` and `anl_id`, validity dates, and Polygon/MultiPolygon geometry. The developer endpoints `/analysis/{id}`, `/areas/{id}/{period}` and `/population/{id}` distinguish specific analyses and periods. Periods `C`, `P` and `A` represent current, projected and second projected assessments. The simplified `/country` route selects a latest-valid assessment period and cannot substitute for a historical current-only series.

The schema declares API-key authentication. No key was requested, extracted from a public application, or used in this audit. An approved key or publisher-provided assessment/area exports would enable the next step: establish analysis/area relationships, compare boundary versions and population groups, reconcile current/projected totals, and preserve every revision. Access alone would not certify compatibility or supply twelve comparable historical years.

## Reproduce

```bash
python -m monitoring.recovery_audit --offline
python -m pytest -q tests/test_recovery_audit.py
# Resume a large legacy download if needed; partial ranges never activate:
python -m monitoring.recovery_audit --recover-legacy-ranges
```

Offline replay verifies archived hashes and regenerates evidence tables. For a fresh investigation, omit `--offline` and use a new `--output` directory to preserve this dated ledger. Live requests have explicit byte and duration bounds. Range recovery requires exact complete coverage and a consistent source version; its command can resume verified chunks. This archive investigation is manual; daily monitoring continues to use its existing source adapters.
