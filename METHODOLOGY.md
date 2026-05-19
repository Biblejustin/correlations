# Methodology

Shared analytical framework used across all 10 repos in this project (`earthquakes`, `spaceweather`, `famines-tracking`, `flood-data`, `pandemics-tracking`, `volcanic-eruptions`, `tropical-cyclones`, `droughts-tracking`, `astronomical-signs`, `correlations`).

This document explains the recurring methodological concepts in one place so each repo's README doesn't have to re-explain them.

---

## 1. Detection-bias-clean bands

Every disaster catalog has a *completeness floor* — a threshold below which events are systematically missed. Below the floor, apparent trends mostly reflect catalog improvement (better satellites, more journalists, denser networks) rather than reality.

For each catalog we pick the cleanest band — one where 100% of events have been catalogued throughout the analysis window. Examples:

| Catalog | Clean band | Why |
|---|---|---|
| USGS earthquakes | M ≥ 7 | Detected globally by every seismograph since 1900 |
| GFZ Kp index | Peak Kp ≥ 7 (G3+ storms) | Disturbs every mid-latitude magnetometer; methodology stable since 1932 |
| GOES X-ray flares | X1+ | Sensors continuously calibrated since 1976 |
| WPF famines | ≥ 100k deaths | Curatorial inclusion threshold |
| Tropical cyclones | ≥ 1000 deaths | Major events get reported regardless of catalog density |
| Volcanoes (Smithsonian GVP) | VEI ≥ 5 | Globally detected since ~1500; VEI ≥ 6 since several millennia |

The "detection-clean band" is the only honest comparison across centuries.

---

## 2. Regime-piecewise detrending

Within the detection-clean band there can still be *regime changes* — moments when the network jumped (WWSSN 1965, ANSS 2000, Dartmouth Flood Observatory 1985, satellite-era Kp). For yearly correlations and trend fits, we subtract a piecewise-linear baseline computed *separately within each regime*, then test the residuals.

The function `piecewise_detrend(series, breakpoints)` in `detection_regimes.py` handles this. Each catalog has canonical breakpoints documented in `REGIMES`.

After detrending, a positive Pearson r between two series means "when one is above its piecewise baseline, the other tends to be above its baseline too" — not just "both rose during the 20th C."

---

## 3. Bootstrap confidence intervals

For any reported correlation, trend slope, or rate, we compute a 95% bootstrap CI by resampling the years 2,000 times with replacement and recomputing the statistic on each sample. The 2.5th and 97.5th percentiles of the bootstrap distribution become the CI bounds.

**Above vs below zero**: when the CI excludes zero, the result is "statistically significant" at the chosen α = 0.05 level. When the CI crosses zero, we can't distinguish the result from chance.

We prefer bootstrap CIs over analytical (t-test) CIs because the underlying time series violate IID assumptions due to autocorrelation; bootstrap is robust to that.

---

## 4. Periodogram peak detection — bootstrap null

A periodogram decomposes a time series into power at each cycle length. The standard way to ask "is this peak meaningfully above noise?" is to construct a null distribution:

- **Bootstrap-resample null**: shuffle the years with replacement and recompute the periodogram many times. The 95th percentile at each frequency is the "noise floor" — peaks above it are real.

- **Phase-randomized null is wrong for peak detection** because it preserves the original power spectrum exactly. We use it only for coherence tests (which depend on phase).

Cells in figure 23's heatmap show `(observed power) / (bootstrap 95% null)` — values ≥ 1.0 mark genuine peaks.

---

## 5. Bonferroni vs FDR multiple-comparison correction

When we run K tests and one returns p < 0.05, we have to ask: is this a real effect, or one of ~K × 0.05 false positives we'd expect by chance? Two standard corrections:

- **Bonferroni**: most conservative. Multiply each raw p by K. Effectively rejects any result not at p < 0.05 / K. Misses real effects in exchange for almost no false positives.

- **FDR (Benjamini-Hochberg)**: more permissive, controls the *expected proportion* of false discoveries among rejections rather than the family-wise error rate. Better when some real effects exist in the data.

Across the 28 pairwise tests in the cross-correlation matrix, only `wars × famines` (r = +0.43, raw p < 0.001) survives both Bonferroni and FDR — and that's the well-known causal mechanism where war causes famine.

---

## 6. z-score normalization and the consensus line

To compare "is this year unusually busy" across categories with vastly different units (deaths, counts, magnitudes), we z-score each series within its detection-clean window: `(x − mean(x)) / std(x)`. A year with z = +2 is "2 standard deviations above this category's normal level."

The **consensus z** (figures 21 and 22) is the average z-score across all available indicators per year. If birth-pain-style synchronization were present, the consensus would spike well above 0 during shared "bad years." Observed maximum: +1.46 in 1991.

---

## 7. Dispersion index (variance-to-mean ratio)

`dispersion_index = var(y) / mean(y)` for yearly counts. The reference value is 1.0 (Poisson process — events arriving independently). Values > 1 indicate **clustering** (events bunch in time); < 1 indicates **regular spacing** (events more even than chance).

Used in `pattern_analysis.py` to test whether disasters arrive in clusters or evenly.

---

## 8. Wavelet coherence (time-resolved coupling)

Standard Pearson r averages over the entire time series — a number like r = +0.43 for wars × famines hides whether the coupling was constant or concentrated in specific eras. **Wavelet coherence** decomposes the relationship into a 2D map: time on the x-axis, period (cycle length) on the y-axis, color = coherence at that (time, period) point.

A "hot zone" at (1940, 10y) means: in the WWII era, wars and famines were coupled at a 10-year-cycle timescale. We use Morlet wavelets and Torrence-Compo smoothing (2-scale Gaussian in time × 1.2-bin triangular in scale).

See figure 25 (wars × famines wavelet coherence) for the headline application.

---

## 9. Tail-event sensitivity (jackknife)

The strongest correlations and trends may depend on a handful of dominant single events (WWII, 1918 Spanish Flu, 1958 Great Chinese Famine, Sumatra+Tōhoku, May 2024 X-class flares). To test robustness, we drop the top-N years (by absolute residual from each series' mean) and recompute the result. If r collapses, the original was driven by tail events; if r holds, the coupling is a steady long-run pattern.

See figure 24 + `sensitivity.py`. Wars↔famines r = +0.43 holds up through dropping top-5 events (drops to +0.25, still significant), but collapses by dropping top-10 (drops to +0.15, no longer significant) — meaning it's a *real but concentrated* signal driven by ~1908-1945 Russian-Civil-War, WWI, and WWII years.

---

## 10. Common reference-line interpretation

Across all plots, any reference line on a chart has a consistent meaning:

| Line | Above means | Below means |
|---|---|---|
| OLS trend line on decadal bars | Above-trend decade | Below-trend decade |
| Constant-rate line on cumulative plot | Events arriving faster than long-run rate (busy stretch) | Slower than long-run rate (quiet stretch) |
| Power-law fit on distribution | More events at this severity than scaling rule predicts (excess) | Fewer than scaling rule predicts |
| Chance-expectation horizontal at 1.0× (window-ratio plots) | More events near target dates than chance | Fewer than chance |
| OLS scatter line | y-value larger than x-value predicts | y-value smaller than x-value predicts |

---

## References

- Torrence, C. & Compo, G. P. (1998). *A practical guide to wavelet analysis.* Bull. Am. Meteorol. Soc.
- Benjamini, Y. & Hochberg, Y. (1995). *Controlling the false discovery rate.* J. R. Statist. Soc. B.
- Cirillo, P. & Taleb, N. (2016). *On the statistical properties and tail risk of violent conflicts.* Physica A.
- Press, W. H. et al. (2007). *Numerical Recipes 3rd edition.* (chapter on spectral analysis)
- The detection-bias-clean band concept generalizes Geller, R. (1985)'s argument about seismic catalog completeness to all disaster catalogs.
