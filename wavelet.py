"""
Descriptive war/famine Morlet wavelet coherence on one observed annual grid.

Every war variant and famine shares the longest finite contiguous overlap.
Missing years are not imputed or compressed. Era summaries exclude the edge
region. Coherence is descriptive: no surrogate significance test or causal
attribution is provided. NPZ stores all cells, phase, periods, and edge mask.
"""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import signal
from statistical_helpers import contiguous_overlap, last_complete_year

from correlate_events import (
    load_yearly_war_deaths_active,
    load_yearly_war_deaths_split,
    load_yearly_famine_deaths_wpf,
)


def cwt_coherence(x, y, scales, dt=1.0):
    """Compute Morlet wavelet coherence between two equal-length series.

    Returns (coherence_matrix, phase_matrix) of shape (n_scales, n_times).
    Smoothing across time and scale follows Torrence & Webster 1999.
    """
    x, y, scales = np.asarray(x, float), np.asarray(y, float), np.asarray(scales, float)
    if x.ndim != 1 or y.shape != x.shape or len(x) < 8:
        raise ValueError("Need equal one-dimensional series with at least eight observations")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Wavelet input contains missing or nonfinite observations")
    if np.std(x) == 0 or np.std(y) == 0 or len(scales) < 3 or np.any(scales <= 0):
        raise ValueError("Wavelet needs variable series and at least three positive scales")
    n = len(x)
    w0 = 6.0  # Morlet base frequency
    Wx = np.zeros((len(scales), n), dtype=complex)
    Wy = np.zeros((len(scales), n), dtype=complex)
    # FFT-based CWT for clean output sizing
    freqs_fft = np.fft.fftfreq(n, d=dt)
    Xf = np.fft.fft(x)
    Yf = np.fft.fft(y)
    for i, s in enumerate(scales):
        # Morlet wavelet in frequency domain
        omega = 2 * np.pi * freqs_fft
        psi_hat = (np.pi ** -0.25) * np.sqrt(2 * np.pi * s) * \
            np.exp(-(s * omega - w0) ** 2 / 2) * (omega > 0)
        Wx[i] = np.fft.ifft(Xf * psi_hat)
        Wy[i] = np.fft.ifft(Yf * psi_hat)

    # Cross-spectrum
    Wxy = Wx * np.conj(Wy) / scales[:, None]
    Sxx = np.abs(Wx) ** 2 / scales[:, None]
    Syy = np.abs(Wy) ** 2 / scales[:, None]

    # Smoothing: Gaussian along time with width 2*scale, plus 1.2-wide along scale.
    # This is the Torrence-Compo standard for wavelet coherence.
    def smooth_time(a, scales):
        n_samples = a.shape[1]
        out = np.zeros_like(a, dtype=complex)
        for i, s in enumerate(scales):
            sigma = max(1.0, 2 * s)
            kernel_size = min(n_samples, max(3, int(6 * sigma)))
            if kernel_size % 2 == 0:
                kernel_size += 1
            t = np.arange(kernel_size) - kernel_size // 2
            kernel = np.exp(-(t ** 2) / (2 * sigma ** 2))
            kernel = kernel / kernel.sum()
            row = a[i]
            # Pad-reflect to avoid edge artifacts
            padded = np.pad(row, kernel_size // 2, mode="reflect")
            conv = np.convolve(padded, kernel, mode="valid")
            out[i] = conv[:n_samples]
        return out

    def smooth_scale(a):
        # Bartlett (triangular) window of width 1.2 scale-bins
        kernel = np.array([0.25, 0.5, 0.25])
        out = np.zeros_like(a, dtype=complex)
        for j in range(a.shape[1]):
            out[:, j] = np.convolve(a[:, j], kernel, mode="same")
        return out

    Wxy_s = smooth_scale(smooth_time(Wxy, scales))
    Sxx_s = smooth_scale(smooth_time(Sxx, scales))
    Syy_s = smooth_scale(smooth_time(Syy, scales))

    coh = np.abs(Wxy_s) ** 2 / (np.real(Sxx_s) * np.real(Syy_s) + 1e-30)
    coh = np.clip(np.real(coh), 0, 1)
    phase = np.angle(Wxy_s)
    return coh, phase


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wars-csv", default="data/wars.csv")
    ap.add_argument("--famines-wpf-csv", default="data/famine_deaths_by_year.csv")
    ap.add_argument("--year-hi", type=int, default=last_complete_year())
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    # Load both series 1900 through requested complete-year cutoff; also split by war type for follow-up panels
    wars = load_yearly_war_deaths_active(args.wars_csv, 1900, args.year_hi)
    famines = load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, args.year_hi)
    wars_intra = load_yearly_war_deaths_split(args.wars_csv, "intrastate", 1900, args.year_hi)
    wars_inter = load_yearly_war_deaths_split(args.wars_csv, "interstate", 1900, args.year_hi)
    aligned = contiguous_overlap({"wars": wars, "famines": famines,
                                  "interstate": wars_inter, "intrastate": wars_intra}, min_years=30)
    wars, famines = aligned["wars"], aligned["famines"]
    wars_inter, wars_intra = aligned["interstate"], aligned["intrastate"]
    logged = np.log10(aligned + 1)
    normalized = (logged - logged.mean()) / logged.std(ddof=0)
    years = aligned.index.to_numpy()
    x, y = normalized["wars"].to_numpy(), normalized["famines"].to_numpy()
    print(f"Observed contiguous overlap: {years[0]}–{years[-1]} ({len(years)} years)")

    # Scales corresponding to periods of 2 to 60 years
    periods = np.logspace(np.log10(2), np.log10(60), 50)
    fourier_factor = 4 * np.pi / (6 + np.sqrt(38))
    scales = periods / fourier_factor

    coh, phase = cwt_coherence(x, y, scales)
    coi_period = np.minimum(years - years[0], years[-1] - years) * fourier_factor / np.sqrt(2)
    reliable = periods[:, None] <= coi_period[None, :]
    np.savez_compressed(out / "25_wavelet_coherence.npz", years=years, periods=periods,
                        coherence=coh, phase=phase, outside_edge_region=reliable)
    metadata = {"start_year": int(years[0]), "end_year": int(years[-1]),
                "n_years": len(years), "finite_cells": int(np.isfinite(coh).sum()),
                "total_cells": int(coh.size), "interpretation": "descriptive; no significance calibration",
                "era_summaries": []}


    # ---- Figure ----
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)

    # Top: time series
    ax = axes[0]
    ax.plot(years, x, color="#cc4422", linewidth=1.4, label="War deaths (log10, z-score)")
    ax.plot(years, y, color="#dd9966", linewidth=1.4, label="Famine deaths (log10, z-score)")
    # Annotate eras
    ax.axvspan(1914, 1923, color="lightyellow", alpha=0.35,
                  label="WWI + civil war + Russian famine")
    ax.axvspan(1939, 1945, color="lightyellow", alpha=0.35,
                  label="WWII + Bengal/Greek/Dutch/Vietnam famines")
    ax.axvspan(1958, 1962, color="lightblue", alpha=0.35,
                  label="Great Chinese Famine (no war)")
    ax.set_ylabel("z-score")
    ax.set_title(f"Wars and famines, log10 deaths, {years[0]}–{years[-1]} — eras shaded")
    ax.legend(loc="upper right", fontsize=8.5, ncol=2)
    ax.grid(axis="y", alpha=0.3)

    # Bottom: wavelet coherence heatmap
    ax = axes[1]
    pcm = ax.pcolormesh(years, periods, coh, cmap="RdBu_r", vmin=0, vmax=1, shading="auto")
    ax.set_yscale("log")
    ax.set_ylabel("Period (years, log)")
    ax.set_xlabel("Year")
    ax.invert_yaxis()
    ax.set_title("Wavelet coherence between war deaths and famine deaths\n"
                  "High coherence describes shared variation; no calibrated significance test.",
                  fontsize=11)
    plt.colorbar(pcm, ax=ax, label="coherence", shrink=0.85)
    # Cone of influence: edge effects beyond +/- 1 scale from edge
    coi_period_eq = coi_period
    ax.fill_between(years, coi_period_eq, periods.max(),
                       color="white", alpha=0.6, label="cone of influence")
    ax.set_ylim(periods.max(), periods.min())

    plt.tight_layout()
    plt.savefig(out / "25_wavelet_coherence_wars_famines.png", dpi=120)
    plt.close()
    print(f"Wrote {out/'25_wavelet_coherence_wars_famines.png'}")

    # Print era-wise mean coherence
    print("\nMean coherence by era (averaged across 5–20yr periods):")
    band_mask = (periods >= 5) & (periods <= 20)
    eras = [(1900, 1913, "Pre-WWI"),
             (1914, 1923, "WWI era"),
             (1924, 1938, "Interwar"),
             (1939, 1945, "WWII era"),
             (1946, 1962, "Post-WWII / GCF"),
             (1963, 1989, "Cold War late"),
             (1990, args.year_hi, "Post-Cold-War")]
    for s, e, name in eras:
        y_mask = (years >= s) & (years <= e)
        sub = np.where(reliable, coh, np.nan)[band_mask][:, y_mask]
        sub = sub[np.isfinite(sub)]
        if sub.size > 0:
            metadata["era_summaries"].append({"era": name, "mean": float(sub.mean()), "peak": float(sub.max()), "n_cells": int(sub.size)})
            print(f"  {name:<20} ({s}-{e}): mean coh = {sub.mean():.3f}, "
                    f"peak = {sub.max():.3f}")

    # Also compute intrastate and interstate coherence with famines and report
    print("\nComparison: wavelet coherence wars vs famines, by war type")
    for label, war_series in [("Combined", wars), ("Interstate (basileia)", wars_inter),
                                ("Intrastate (ethnos)", wars_intra)]:
        x_l = np.log10(war_series.values + 1)
        x_l = (x_l - x_l.mean()) / x_l.std()
        coh_split, _ = cwt_coherence(x_l, y, scales)
        for s, e, era_name in eras:
            y_mask = (years >= s) & (years <= e)
            sub = np.where(reliable, coh_split, np.nan)[band_mask][:, y_mask]
            sub = sub[np.isfinite(sub)]
            if sub.size > 0:
                print(f"  {label:<28} {era_name:<18}: mean coh = {sub.mean():.3f}")

    (out / "25_wavelet_results.json").write_text(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
