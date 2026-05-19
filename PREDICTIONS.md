# Pre-registered predictions

Locking in specific quantitative predictions as of **2026-05-19** for revisit at 2030, 2035, and 2040.

The purpose is to make the analysis falsifiable going forward. If the birth-pains hypothesis is correct, certain predictions follow; if it's not, different ones do. By recording them now, neither side can shift the goalposts later.

---

## 1. Contractions

Current detected contractions (multi-year periods of high consensus z):
1. 1916–1920 (peak z = 0.52)
2. 1939–1945 (peak z = 0.45)
3. 2011–2013 (peak z = 0.34)
4. 2022–2025 (peak z = 0.30) — ongoing as of 2026

### Birth-pains predictions for 2030 revisit:

**P1.** A 5th contraction will be detected with start year between 2027 and 2032.
- *Birth-pains expectation:* TRUE (gaps shrinking).
- *Null expectation:* uncertain — gap distribution has been highly irregular (19, 66, 9 years).

**P2.** The 5th contraction's peak rolling z will exceed 0.34 (matching or exceeding the 2011–13 peak).
- *Birth-pains expectation:* TRUE (intensification).
- *Null expectation:* FALSE — recent contractions have been trending down (0.52 → 0.45 → 0.34 → 0.30).

**P3.** The gap between the end of the 2022–25 contraction and the start of the 5th will be ≤ 9 years.
- *Birth-pains expectation:* TRUE (shrinking gaps).
- *Null expectation:* uncertain.

### Revisit at 2035 / 2040:

**P4.** By 2035: at least 6 distinct contractions total since 1900, with average inter-contraction gap < 15 years.
**P5.** By 2040: peak rolling z of the most recent contraction exceeds 0.40.

---

## 2. Trends — directional predictions

For each indicator, the trend direction in its detection-clean window (point estimate as of 2026):

| Indicator | Current trend (%/decade) | Birth-pains prediction (2035) | Detection-trend-down prediction (2035) |
|---|---|---|---|
| Cyclone deaths (1950+) | +48.7% | Continues to rise | Begins to flatten as warning systems improve |
| X1+ flares (cyclic) | +43.1% | n/a — cyclic, not secular | Will moderate after Cycle 25 peak |
| Pandemic deaths (1900+) | +10.6% | Continues to rise | Flat (HIV/COVID were specific events) |
| M ≥ 7 quakes (1900+) | +1.7% | Continues to rise | Flat (M ≥ 8 control is flat) |
| War deaths (1900+) | +7.2% (NS) | Becomes significantly positive | Stays flat |
| Famine deaths (1900+) | −14.7% (NS) | Reverses to positive | Stays flat or further declines |
| Flood deaths (1985+) | −14.6% (NS) | Reverses to positive | Stays flat or further declines |
| VEI ≥ 5 (1900+) | −2.1% (NS) | n/a — no expected change | Flat |
| Drought intensity (1850+) | +4.4% | Continues to rise | Flat in satellite era |

**P6.** By 2035: at least 6 indicators (out of 14) show significantly rising trends (CI excludes 0 above zero) in their detection-clean windows.
- *Currently:* 4 indicators are significantly rising (cyclone deaths, X1+ flares, pandemic deaths, marginally M≥7 quakes).
- *Birth-pains expectation:* TRUE.

**P7.** By 2035: the famine-deaths trend (full-span) reverses to positive at p < 0.05.
- *Currently:* point estimate −14.7%/decade, CI crosses 0.
- *Birth-pains expectation:* TRUE.

---

## 3. Wars↔famines coupling

**P8.** The wars↔famines detrended Pearson r will remain ≥ +0.30 through 2035.
- *Currently:* +0.43 over 1900–2025; +0.25 if dropping top-5 tail events.
- *Birth-pains expectation:* TRUE or stronger (more war-induced famines: Syria, Yemen, Sudan, Gaza, Tigray).
- *Long-peace expectation:* FALSE — r drifts down as conflicts decouple from famines via aid.

**P9.** Wavelet coherence at 5–20y periods recovers to ≥ 0.50 by 2035 (currently ~0.35 in the post-Cold-War era, 0.61 in WWI era).

---

## 4. Solar–disaster periodicity

**P10.** The drought × 11-year periodogram peak (currently 3.26× null) will remain significant in updated runs through 2035.
- *Currently:* 3.26× peak at 10.4y.
- *Birth-pains expectation:* n/a (this is a paleoclimate effect, not a birth-pains claim).
- *Climate prediction:* TRUE — the solar-cycle modulation of drought via jet-stream is a robust paleoclimate finding.

**P11.** No new indicator (wars, famines, pandemics, floods, cyclones, earthquakes, volcanoes, refugees, economic crises, coups) will develop a significant 11-year peak by 2035.
- *Currently:* all non-solar, non-drought indicators are below the noise floor at 11y.
- *Birth-pains expectation:* uncertain (the birth-pains hypothesis doesn't specifically predict solar cycling).

---

## 5. Methodological commitments

To prevent post-hoc reframing:

**M1.** Analyses will be re-run at 2030, 2035, 2040 with the SAME scripts (`analyze.py`, `trends_meta.py`, `signs_overlay.py`, `contractions_analysis.py`, `pattern_analysis.py`, `periodogram_extended.py`, `wavelet.py`, `chains.py`, `sensitivity.py`, `meta_analysis.py`).

**M2.** New indicators added between now and revisit dates will be analyzed *both* including and excluding them, so trend changes can be attributed to new data rather than new methodology.

**M3.** If any current null finding becomes significant, the headline result was wrong and the README will be updated to say so explicitly.

**M4.** If any current significant finding becomes null, same — the README will update to "this no longer holds."

---

## How to revisit

```bash
git clone https://github.com/Biblejustin/correlations.git
cd correlations
# Re-fetch all source catalogs (each source repo has fresh data)
... see Reproducing the plots in each repo's README ...
# Run the full analysis pipeline
make all  # or bash run-all.sh
# Compare to PREDICTIONS.md predictions at the relevant revisit year
```

Score each prediction as TRUE / FALSE / UNDETERMINED and update this document with the verdict.
