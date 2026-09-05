"""
Build a single composite headline image showing 6 key figures from the analysis.

Combines figures 18, 19, 22, 23, 25, 27 into a 3×2 grid you can share
without anyone having to read the README. Each panel keeps its original
title; the composite adds a master heading and a one-paragraph summary at
the bottom.

Reads existing PNG figures from figures/ and writes figures/32_dashboard.png.
"""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.image import imread


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--figures-dir", default="figures")
    ap.add_argument("--out", default="figures/32_dashboard.png")
    args = ap.parse_args()
    figs_dir = Path(args.figures_dir)

    panels = [
        ("18_cross_correlation_matrix.png", "Annual cross-correlation family",
         "Effect sizes with serial-dependence sensitivity and correction across 45 pairs."),
        ("19_trends_meta_comparison.png", "Trends per indicator",
         "Coverage and units differ; selected-event catalogs cannot establish complete hazard rates."),
        ("22_contractions.png", "Fixed-domain composite eligibility",
         "Missing flood/drought baseline observations make current composite unavailable."),
        ("23_periodogram_extended.png", "Annual spectral sensitivity",
         "AR(1) surrogates repeat the frequency search; peaks alone do not identify solar influence."),
        ("25_wavelet_coherence_wars_famines.png", "Wars and famines through time",
         "Finite contiguous overlap; edge regions excluded. Coherence is descriptive."),
        ("20_pattern_birthpains.png", "Event frequency, waiting times and clustering",
         "Exact event times retained where available; annual catalogs use annual-rate diagnostics."),
    ]

    fig = plt.figure(figsize=(20, 26))
    fig.suptitle("Correlations project — headline dashboard\n"
                  "Measured patterns, explicit coverage, corrected exploratory tests",
                  fontsize=18, y=0.995, weight="bold")

    for i, (filename, title, caption) in enumerate(panels):
        ax = fig.add_subplot(3, 2, i + 1)
        path = figs_dir / filename
        if not path.exists():
            ax.text(0.5, 0.5, f"missing: {filename}", ha="center", va="center")
            ax.axis("off")
            continue
        img = imread(path)
        ax.imshow(img)
        ax.axis("off")
        ax.set_title(f"{i + 1}. {title}", fontsize=13, weight="bold", pad=8)
        # Caption beneath
        ax.text(0.5, -0.02, caption, ha="center", va="top",
                  transform=ax.transAxes, fontsize=10, style="italic", color="#444444",
                  wrap=True)

    fig.text(0.5, 0.015,
              "Historical associations are exploratory. Unavailable data do not mean zero events.\n"
              "Biblical themes guide monitoring questions; these statistics do not establish prophetic fulfillment.\n"
              "Regional food, displacement, disease, religion and Israel water outputs: results/monitoring/monitoring_report.md",
              ha="center", va="bottom", fontsize=10, color="#222222")

    plt.tight_layout(rect=(0.02, 0.04, 0.98, 0.97))
    plt.savefig(args.out, dpi=110, bbox_inches="tight")
    plt.close()
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
