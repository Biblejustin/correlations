# Backlog

Analytical improvements identified during the work but not currently implemented. Each is a self-contained piece of work that would strengthen the existing analysis.

---

## 1. Extreme tail-event sensitivity analysis

**Status:** ✅ **DONE 2026-05-19.** See `sensitivity.py` and figure 24 in the correlations repo. Key result: wars × famines r = +0.43 holds through dropping top-5 events (drops to +0.25, still significant) but collapses by top-10 (+0.15, no longer significant). Real but concentrated signal driven by 1908–1945 war-famine clustering. The X1+ flare trend is the most tail-sensitive (drops from +1.4/dec to +0.4/dec when dropping top-5 — confirming the "cyclic, not secular" caveat).

Single very large events dominate yearly counts in several indicators:
- **WWII (1939–45)** dominates war deaths — without those 7 years the war-deaths trend over the 20th C reverses direction.
- **1958 Great Chinese Famine** alone accounts for the bulk of post-WWII famine deaths.
- **1918 Spanish Flu** carries the pre-COVID pandemic distribution.
- **1755 Lisbon earthquake** (M~8.7, ~50k deaths) would dominate any pre-1900 quake catalog if we extended back that far.
- **1859 Carrington event** is the only G5-equivalent in pre-modern records and exceeds modern peak Kp values.
- **2004 Sumatra (M9.1)** and **2011 Tōhoku (M9.1)** together account for ~25% of M≥8 quake count in the modern era.
- **May 2024 X-class swarm** drives nearly all of the 2024 datapoint in the flares-vs-everything scatter plots.

**Implementation:**

1. **Jackknife** — for each indicator, recompute every reported trend/correlation/CI after dropping the top 1 / top 3 / top 5 single-year contributors. Compare to the all-data result.
2. **Influence function / Cook's distance equivalent** for the cross-correlation matrix — which years' removal changes the wars-×-famines r=+0.43 result most? (Likely 1942–45.)
3. **Bootstrap with weighted resampling** — give Bernoulli weights to each year and recompute, rather than uniform bootstrap which already handles this implicitly but doesn't surface which years are decisive.
4. **Report a "robustness score"** per result: % of jackknife iterations where the conclusion (CI excludes 0 / survives FDR / matches direction) holds.

**Expected deliverable:** new figure `24_tail_event_sensitivity.png` and a small section in the README under Caveats. New script `sensitivity.py` that wraps the existing analyses with a `--drop-top-n` flag.

**Why it matters:** several of the reported results may hinge on 2–4 specific historical events. The reader should know which results are genuinely "the long-run pattern" and which are "WWII + a couple of others."

---

## 2. Continued contraction monitoring

**Status:** Conceptual; depends on future data.

The contraction-period analysis identified 4 multi-year clusters (1916–20, 1939–45, 2011–13, 2022–25) but the birth-pains "intensification + shrinking gaps" prediction is underpowered with only n=4 contractions and n=3 gaps. A 5th contraction by ~2030 with peak rolling z > 0.30 would be the first datapoint clearly consistent with both predictions.

**Action:** rerun `contractions_analysis.py` periodically as new data arrives.

---

## 3. Replace hand-curated CSVs with canonical published datasets where possible

**Status:** ⏳ **Partial — substantial progress 2026-05-19.** Authoritative sources now in use:
- ✅ Famines: WPF/OWID via `famines-tracking` repo
- ✅ Floods: Dartmouth + EM-DAT via `flood-data` repo
- ✅ **Wars: UCDP/PRIO Armed Conflict Dataset v24.1 (2,686 conflict-years 1946-2023)** added as `data/ucdp_prio_conflicts.csv`. See `ucdp_compare.py` and figure 30. The canonical source dramatically strengthens the *ethnos epi ethnos* result: intrastate conflicts +4.66/decade [CI +1.85, +7.67] vs hand-curated +0.038/decade (CI nearly crossing 0). Both agree on direction; UCDP shows the rise is far more statistically significant.

Remaining and blocked:
- ❌ **Brecke Conflict Catalog (1400-2000)**: original Georgia Tech URL returns 404; mirrors also gone. **Permanently unavailable** as of 2026-05-19.
- ❌ **Smithsonian GVP eruption catalog**: server returned HTTP 403 even via proxy. Bot-protected.
- ❌ **OWID pandemic mortality CSV**: grapher URL returns 404 regardless of proxy. **URL has changed; would need re-investigation.**
- ✅ **NOAA NGDC catalogs**: now reachable via Webshare proxy. **Successfully fetched**:
  - `noaa_significant_earthquakes.csv` — 4,200 events, 2150 BCE → 2005
  - `noaa_volcanic_events.csv` — 900 events, 4360 BCE → 2026
- ✅ **COW v4 (Correlates of War)**: now reachable via proxy. Successfully fetched:
  - `cow_interstate_wars_v4.csv` — 95 unique wars 1823-2003
  - `cow_intrastate_wars_v4.csv` — ~700 events 1816+
  - `cow_extrastate_wars_v4.csv` — 198 rows

See `canonical_compare.py` and figure 31 for the comparison. The headline ethnos/basileia finding holds in both source families.

---

## 4. Regional disaggregation

**Status:** ✅ **DONE 2026-05-19 for droughts AND earthquakes.**

Droughts (`regional.py`, figure 29): the global drought-×-11y peak (3.26× null) is carried strongest by **South Asia (3.03×)**, Europe (2.96×), East Asia (2.61×), and weakest by **North America (0.11×, NS)** — opposite to the conventional paleoclimate literature emphasis on the western US.

Earthquakes (`regional_quakes.py`, figure 33): NGDC M≥7 catalog 1900-2005 split by NOAA `regionCode` into tectonic groups (Pacific Ring of Fire, Alpide belt, Indo-Asian, Caribbean, Atlantic/MOR, African/rift). Key results:
- **Global NGDC M≥7 trend is SIGNIFICANTLY DECLINING at −0.28 events/decade** (CI [−0.49, −0.07]) — contrast with USGS-derived global +1.7%/decade. NGDC is selection-biased toward consequential events (deaths/damage/tsunami) so declining trend partly reflects improved building codes + warning systems, paralleling the cyclone-deaths-flat post-1985 story.
- **Pacific Ring of Fire trend: −0.25/decade** (CI excludes 0) — drives the global decline.
- **Indo-Asian region (Indonesia + India): 1.51× null at 11.8y** — the only region with a modest 11y peak above noise floor. With n=60 and one significant region out of four tested, multiple-comparison concerns apply.
- Alpide belt and Caribbean show no 11y signal.

Global yearly counts may average out regional patterns. The Israel-Levant analysis already does this for one region. Could be extended:

- Subduction-zone quakes (Pacific Ring of Fire) vs intraplate
- Bay-of-Bengal cyclones vs Atlantic vs Pacific
- Sahel/Horn-of-Africa droughts vs global
- Regional war frequency (Europe vs Asia vs Africa)

Would let us ask "does the solar cycle affect drought differently in different regions?" The drought ×11y peak likely comes mostly from specific regions (western US, Mexico, Africa).

---

## 5. Wavelet coherence (time-resolved coupling)

**Status:** ✅ **DONE 2026-05-19.** See `wavelet.py` and figure 25. Key result: the wars × famines coupling was strongest pre-WWII (mean coherence ~0.61), nearly absent during the Cold War (~0.17 — the "long peace" decoupled them), partial recovery post-1990 (~0.35) as war-driven famines (Syria, Yemen, Tigray, Sudan, Gaza) returned. The full-span r = +0.43 hides this temporal structure.

The current coherence test (figure 05) measures a single coherence value at each frequency over the full span. Wavelet coherence (continuous, time-localized) would reveal whether, e.g., the wars-↔-famines coupling was stronger during specific eras (WWII?) than the time-averaged r = +0.43 suggests.

**Why it matters:** time-resolved coupling could reveal patterns hidden by full-span averages, particularly for indicators with regime changes mid-record.

---

## 6. Granger-causality tests on the wars-famines pair

**Status:** ✅ **DONE 2026-05-19.** See `granger.py` and figure 28. Key result: wars Granger-cause famines at lags 1, 2, and 5 (p < 0.05); the reverse direction is never significant (all p > 0.17). The direction is asymmetric — wars predict future famines, not the reverse. The combined series gives the strongest signal; split-by-war-type signals are weaker due to reduced power.

The wars-famines r = +0.43 is the only FDR-surviving correlation in the cross-correlation matrix. We've inferred direction from the well-established causal mechanism (war causes famine), but a formal Granger causality test on the detrended time series would put numbers on it.

**Why it matters:** confirms the causal direction quantitatively rather than from physical intuition.

---

## 7. Add additional indicator categories

**Status:** ⏳ **Partial.** Three indicators added 2026-05-19:

- ✅ **Refugees / mass displacement** — `data/refugees.csv`, ~40 events 1915–2025
- ✅ **Economic crises** — `data/economic_crises.csv`, ~45 events 1797–2023 (Reinhart-Rogoff-style)
- ✅ **Coups d'état** — `data/coups.csv`, ~75 events 1950–2023 (Powell-Thyne-style)

Still open candidates:

- ✅ **Heat waves** — DONE 2026-05-19. `data/heat_waves.csv` with 25 events 1896-2024. Trend: **+99.5%/decade since 1980** (fastest-rising indicator in the project).
- ✅ **Terrorism** — DONE 2026-05-19. `data/terrorism.csv` from OWID/GTD aggregator, 1970–2021 (1993 missing — known GTD data-loss gap), 211k events, 488k deaths, peak 2014 (ISIS). Threaded through `trends_meta`, `signs_overlay`, `contractions_analysis`, `periodogram_extended`, `pattern_analysis`, and `meta_analysis` (cross-correlation matrix). Trend: **+92.4%/decade for deaths in the 1998+ post-methodology-shift window** (2nd fastest after heat waves). No 11-year peak (0.62× null at 11.2y). No FDR-significant correlation with any other indicator in the cross-correlation matrix. Adding terrorism to the contractions consensus drops the marginal 1930–33 and 1990–93 contractions just below the 0.25 threshold — the four robust contractions (1918–21, 1940–44, 2009–14, 2019–22) remain.
- ✅ **Stock market crashes** — DONE 2026-05-19. `data/stock_crashes.csv`: 24 bear markets 1906–2025, S&P 500 / DJIA / pre-1957 Cowles index peak-to-trough drawdowns ≥ 20%. Biggest: 1929 Great Depression (86.2%). Threaded through all six multi-indicator scripts. Trend: **flat** (count −1.8%/decade NS; intensity +2.7%/decade NS; both CIs cross 0). No 11y peak (0.99× null at 10.5y). Pattern: neither accelerating nor clustered. **Cross-correlation matrix (10 indicators, 45 tests)**: crashes are independent of every other indicator at FDR. Most negatively correlated to X1+ flares (r = −0.27, raw p = 0.06, NS after FDR) — note this is opposite to "solar minimum causes crashes" claims. Wars × famines remains the only FDR-significant correlation across now 45 tests.
- **Mass extinction / biodiversity loss events** — *skipped* (poor fit for yearly-series framework; geological timescales).

## 8. Cross-category chain analyses

**Status:** ✅ **DONE 2026-05-19.** See `chains.py` and figure 26. Lag-correlation tests on six chain hypotheses. Significant findings:
- Drought → famine deaths peaks at lag +10y (r = +0.22)
- War → famine deaths at lag 0 (r = +0.43)
- War → refugees at lag +9y (r = +0.28)
- War → flood-deaths at lag +2y (r = −0.29, opposite direction — war zones lose flood reporting)
- Economic crisis → coups at lag +1y (r = +0.20, marginal)
- Volcano → famine at lag +3y (NS — Tambora-mechanism doesn't show in post-1900 catalog)
