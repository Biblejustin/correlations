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

**Status:** Partially done (famines + floods now use authoritative WPF / Dartmouth + EM-DAT sources). Remaining:

- **Wars**: currently hand-curated from Brecke + COW + UCDP/PRIO knowledge. The full Brecke Conflict Catalog (~3,700 events) would meaningfully increase statistical power. The CSV is publicly available but was not accessible from this sandbox.
- **Volcanoes**: hand-curated from Smithsonian GVP. The full GVP dataset has ~10,000 eruptions with VEI ≥ 0 — more than we need but the canonical source.
- **Pandemics**: hand-curated. The Our World in Data pandemic mortality dataset is the closest canonical source.

**Why it matters:** replaces "my judgment of which events are major" with "a published research consensus."

---

## 4. Regional disaggregation

**Status:** ✅ **DONE 2026-05-19 for droughts.** See `regional.py` and figure 29. Key result: the global drought-×-11y peak (3.26× null) is carried strongest by **South Asia (3.03×)**, Europe (2.96×), East Asia (2.61×), and weakest by **North America (0.11×, NS)** — opposite to the conventional paleoclimate literature emphasis on the western US. Earthquake regional disaggregation remains open.

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
- **Stock market crashes** (S&P 500 drawdowns ≥ 20%, separable from full financial crises)
- **Major terrorism events** (GTD database)
- **Mass extinction / biodiversity loss events** (very long timescale)

## 8. Cross-category chain analyses

**Status:** ✅ **DONE 2026-05-19.** See `chains.py` and figure 26. Lag-correlation tests on six chain hypotheses. Significant findings:
- Drought → famine deaths peaks at lag +10y (r = +0.22)
- War → famine deaths at lag 0 (r = +0.43)
- War → refugees at lag +9y (r = +0.28)
- War → flood-deaths at lag +2y (r = −0.29, opposite direction — war zones lose flood reporting)
- Economic crisis → coups at lag +1y (r = +0.20, marginal)
- Volcano → famine at lag +3y (NS — Tambora-mechanism doesn't show in post-1900 catalog)
