"""
Wavelet coherence on the wars↔famines pair (the FDR-significant result).

Full-span Pearson r = +0.43 is a single number that averages over the entire
1900-2025 span. Wavelet coherence is time-resolved: it computes coherence
between two series at each (time, frequency) point, revealing whether the
coupling is constant over time or concentrated in specific eras.

Hypothesis: the wars↔famines coupling is likely strongest during the
WWI-WWII era (1914-1945) when major wars caused major famines (Russian
Civil War + Volga famine; Bengal famine 1942; Greek famine 1941; Dutch
Hunger Winter; Vietnamese famine). It probably weakens after 1945.

Implementation uses Morlet wavelets via scipy. Phase difference at the
coherence peak indicates lead/lag.

Writes figures/25_wavelet_coherence_wars_famines.png.
"""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import signal

from correlate_events import (
    load_yearly_war_deaths_active,
    load_yearly_famine_deaths_wpf,
)


def cwt_coherence(x, y, scales, dt=1.0):
    """Compute Morlet wavelet coherence between two equal-length series.

    Returns (coherence_matrix, phase_matrix) of shape (n_scales, n_times).
    Smoothing across time and scale follows Torrence & Webster 1999.
    """
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
    Wxy = Wx * np.conj(Wy)
    Sxx = np.abs(Wx) ** 2
    Syy = np.abs(Wy) ** 2

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
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    # Load both series 1900-2025
    wars = load_yearly_war_deaths_active(args.wars_csv, 1900, 2025)
    famines = load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, 2025)
    wars_log = np.log10(wars + 1).values
    famines_log = np.log10(famines + 1).values
    years = wars.index.values

    # Normalize (zero mean, unit variance)
    x = (wars_log - wars_log.mean()) / wars_log.std()
    y = (famines_log - famines_log.mean()) / famines_log.std()

    # Scales corresponding to periods of 2 to 60 years
    periods = np.logspace(np.log10(2), np.log10(60), 50)
    scales = periods / (2 * np.pi / 6.0)  # Morlet w0=6 conversion

    coh, phase = cwt_coherence(x, y, scales)

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
    ax.set_title("Wars and famines, log10 deaths, 1900-2025 — eras shaded")
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
                  "Red = coupled at that (year, period); blue = uncoupled. "
                  "Look for hot zones in WWI / WWII / Great Chinese Famine.",
                  fontsize=11)
    plt.colorbar(pcm, ax=ax, label="coherence", shrink=0.85)
    # Cone of influence: edge effects beyond +/- 1 scale from edge
    coi = np.minimum(years - years[0], years[-1] - years) * np.sqrt(2)
    coi_period_eq = coi
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
             (1990, 2025, "Post-Cold-War")]
    for s, e, name in eras:
        y_mask = (years >= s) & (years <= e)
        sub = coh[band_mask][:, y_mask]
        if sub.size > 0:
            print(f"  {name:<20} ({s}-{e}): mean coh = {sub.mean():.3f}, "
                    f"peak = {sub.max():.3f}")


if __name__ == "__main__":
    main()
