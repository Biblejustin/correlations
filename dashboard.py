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
        ("18_cross_correlation_matrix.png",
         "Cross-correlation matrix",
         "Only wars × famines (+0.43) survives FDR. Everything else is noise."),
        ("19_trends_meta_comparison.png",
         "Trends per indicator",
         "Cyclones/pandemics/quakes rising; wars/volcanoes flat; floods/famines lean down."),
        ("22_contractions.png",
         "Contractions in time",
         "Six multi-year clusters. 2019–25 is the longest (7yr) and most intense."),
        ("23_periodogram_extended.png",
         "Periodogram (11-yr solar cycle hunt)",
         "Only solar indicators + droughts carry an 11y peak. Everything else is flat."),
        ("25_wavelet_coherence_wars_famines.png",
         "Wars × famines coupling over time",
         "Strongest pre-WWII (0.6), weakest in Cold War (0.17), recovering post-1990."),
        ("27_wars_split_ethnos_basileia.png",
         "Wars split: ethnos vs basileia",
         "Intrastate (ethnos) rising; interstate (basileia) flat. Matches Mt 24:7 doubling."),
    ]

    fig = plt.figure(figsize=(20, 26))
    fig.suptitle("Correlations project — headline dashboard\n"
                  "Disasters, wars, famines, pestilences, signs — pattern analysis across 10 catalogs",
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

    # Master footer text
    fig.text(0.5, 0.015,
              "Headline finding: across ~200 statistical tests, only wars↔famines covary above noise (FDR-significant, r = +0.43). "
              "Wars precede famines (Granger). The Greek doubling holds half-and-half: intrastate (ethnos) is rising; interstate (basileia) is flat. "
              "Birth-pains pattern (acceleration + shrinking gaps + clustering) is detected for some indicators but never all three together. "
              "Reproducible scripts + 10 source repos + PREDICTIONS.md for 2030/2035/2040 revisit at github.com/Biblejustin/correlations.",
              ha="center", va="bottom", fontsize=10, color="#222222",
              wrap=True, style="italic")

    plt.tight_layout(rect=(0.02, 0.04, 0.98, 0.97))
    plt.savefig(args.out, dpi=110, bbox_inches="tight")
    plt.close()
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
