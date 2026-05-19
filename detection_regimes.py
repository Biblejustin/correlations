"""
Detection-regime piecewise trend fitting.

For each historical catalog, completeness has well-known breakpoints — moments
when the recording network changed enough that count differences across the
break are mostly artifact, not signal. This module:

  1. Defines the canonical breakpoints per catalog
  2. Fits a separate linear trend within each segment
  3. Returns the per-segment-detrended residuals (the "real" variation after
     removing the network upgrades)

Use the detrended residuals for any correlation test where a positive raw
correlation could be explained by both series growing because they're both
better recorded.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

# Canonical completeness breakpoints. Year is the first year of the new regime.
REGIMES = {
    # USGS M>=7 globally complete from ~1900 (per earthquakes/README.md).
    # M>=4 has breaks at WWSSN (1965) and ANSS (2000).
    "quakes_m7": [1900],
    "quakes_m4": [1965, 2000],

    # COW interstate wars cleanly back to 1816 (its own start). Brecke pre-1816.
    # Recording density improves with mass media (~1850), then radio (~1920),
    # then television (~1960), then internet (~1995). For yearly count series
    # the most defensible breakpoints are catalog handoffs:
    "wars_global": [1816, 1946, 1989],  # COW start, UCDP start, post-Cold-War

    # WPF famine list starts 1870; pre-1870 is heavy gap.
    "famines": [1870, 1945, 1985],  # WPF start, post-WWII, FEWS-NET-era

    # GOES X-ray sensor came online 1975; before that, H-alpha only.
    "flares_x": [1975],

    # Floods: EM-DAT pre-1985 severely undercounts; Dartmouth Flood Observatory
    # (satellite era) starts 1985. For >=1000-deaths events, EM-DAT is mostly
    # complete from ~1950.
    "floods": [1950, 1985],

    # Pandemics: pre-1900 anecdotal; WHO-monitored 1950+
    "pandemics": [1500, 1900, 1950],

    # Volcanoes: VEI>=5 detection-clean since ~1500 globally; ~1850 for
    # remote regions
    "volcanoes": [1500, 1850, 1950],

    # Cyclones: pre-1850 fragmentary; aircraft recon 1944+; satellite 1979+
    "cyclones": [1850, 1944, 1979],

    # Astronomical: detection independent of network upgrades (celestial mechanics)
    # but recording bias is real in pre-modern era
    "astro": [1500, 1900],
}


def piecewise_detrend(series: pd.Series, breakpoints: list[int]) -> pd.Series:
    """
    Fit separate linear trends within each segment defined by breakpoints,
    return the residual series.

    `series` is indexed by integer year.
    `breakpoints` is a list of segment-start years (sorted ascending).
    """
    s = series.dropna().astype(float)
    if s.empty:
        return series.copy()

    # Determine segment for each index
    years = np.array(s.index, dtype=int)
    segments = np.zeros_like(years)
    for bp in sorted(breakpoints):
        segments += (years >= bp).astype(int)

    out = s.copy()
    for seg in np.unique(segments):
        mask = segments == seg
        if mask.sum() < 3:
            # too few points to fit, leave alone (subtract mean)
            out.iloc[np.where(mask)[0]] = s.iloc[np.where(mask)[0]] - s.iloc[np.where(mask)[0]].mean()
            continue
        x = years[mask]
        y = s.values[mask]
        slope, intercept = np.polyfit(x, y, 1)
        out.iloc[np.where(mask)[0]] = y - (slope * x + intercept)
    return out.reindex(series.index)


def fit_regimes(series: pd.Series, breakpoints: list[int]):
    """Return list of dicts: per-segment slope/intercept/years/fit."""
    s = series.dropna().astype(float)
    years = np.array(s.index, dtype=int)
    segments = np.zeros_like(years)
    for bp in sorted(breakpoints):
        segments += (years >= bp).astype(int)
    fits = []
    for seg in np.unique(segments):
        mask = segments == seg
        x = years[mask]
        y = s.values[mask]
        if mask.sum() < 3:
            fits.append({
                "year_lo": int(x.min()) if mask.sum() else None,
                "year_hi": int(x.max()) if mask.sum() else None,
                "slope": float("nan"), "intercept": float("nan"),
                "n": int(mask.sum()),
            })
            continue
        slope, intercept = np.polyfit(x, y, 1)
        fits.append({
            "year_lo": int(x.min()),
            "year_hi": int(x.max()),
            "slope": float(slope),
            "intercept": float(intercept),
            "n": int(mask.sum()),
        })
    return fits


def bonferroni_correct(p_values: list[float], n_tests: int = None) -> list[float]:
    """Bonferroni-corrected p-values; cap at 1.0. If n_tests omitted, uses len."""
    n = n_tests if n_tests is not None else len(p_values)
    return [min(p * n, 1.0) for p in p_values]
