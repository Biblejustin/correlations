"""
Canonical-source comparison.

Through the Webshare proxy we successfully fetched:
  - NOAA NGDC Significant Earthquakes (4,200 events, 2150 BCE → 2005)
  - NOAA NGDC Significant Volcanic Events (900 events, 4360 BCE → 2026)
  - COW Interstate Wars v4 (95 wars, 1823-2003)
  - COW Intrastate Wars v4.1 (~700 events)
  - COW Extra-state Wars v4
  - UCDP/PRIO Armed Conflict (2,686 conflict-years 1946-2023; already in repo)

This script compares hand-curated catalogs against canonical sources for:
  - M≥7 quakes: USGS 1900+ vs NGDC 2150 BCE–2005
  - VEI≥5 eruptions: hand-curated 1500+ vs NGDC volcanic events 4360 BCE–present
  - Interstate wars: hand-curated 1400+ vs COW v4 1823+ vs UCDP 1946+

Writes figures/31_canonical_compare.png.
"""
import argparse
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from correlate_events import (
    load_yearly_quakes_m7,
    load_yearly_volcanoes,
    load_yearly_wars,
    load_yearly_wars_split,
    load_yearly_noaa_quakes,
    load_yearly_noaa_volcanic_events,
    load_yearly_cow_wars,
    load_yearly_ucdp_conflicts,
)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eq-db-1900", default="../earthquakes/quakes_1900.sqlite")
    ap.add_argument("--noaa-quakes-csv", default="data/noaa_significant_earthquakes.csv")
    ap.add_argument("--noaa-volcanoes-csv", default="data/noaa_volcanic_events.csv")
    ap.add_argument("--volcanoes-csv", default="data/volcanoes.csv")
    ap.add_argument("--wars-csv", default="data/wars.csv")
    ap.add_argument("--cow-inter-csv", default="data/cow_interstate_wars_v4.csv")
    ap.add_argument("--ucdp-csv", default="data/ucdp_prio_conflicts.csv")
    ap.add_argument("--out", default="figures")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    # ---- Quakes ----
    usgs_m7 = load_yearly_quakes_m7(args.eq_db_1900, 1900, 2025)
    noaa_m7 = load_yearly_noaa_quakes(args.noaa_quakes_csv, -2150, 2025, mag_min=7.0)
    noaa_m7_modern = load_yearly_noaa_quakes(args.noaa_quakes_csv, 1900, 2005, mag_min=7.0)

    print(f"USGS M≥7 (1900-2025):  {int(usgs_m7.sum())} events, "
          f"{int(usgs_m7.mean()*10)}/decade avg")
    print(f"NGDC M≥7 full (2150 BCE-2005): {int(noaa_m7.sum())} events")
    print(f"NGDC M≥7 (1900-2005, overlap): {int(noaa_m7_modern.sum())} events vs USGS {int(usgs_m7.loc[1900:2005].sum())}")

    # ---- Volcanoes ----
    hc_volc_5 = load_yearly_volcanoes(args.volcanoes_csv, 1500, 2025, vei_min=5)
    noaa_volc = load_yearly_noaa_volcanic_events(args.noaa_volcanoes_csv, 1500, 2025, deaths_min=0)
    noaa_volc_deadly = load_yearly_noaa_volcanic_events(args.noaa_volcanoes_csv, 1500, 2025, deaths_min=100)

    print(f"\nHand-curated VEI≥5 (1500-2025): {int(hc_volc_5.sum())}")
    print(f"NGDC volcanic events (1500-2025, all): {int(noaa_volc.sum())}")
    print(f"NGDC ≥100-death volcanic events (1500+): {int(noaa_volc_deadly.sum())}")

    # ---- Wars ----
    hc_inter = load_yearly_wars_split(args.wars_csv, "interstate", 1816, 2003)
    cow_inter = load_yearly_cow_wars(args.cow_inter_csv, 1816, 2003, "interstate")
    ucdp_war = load_yearly_ucdp_conflicts(args.ucdp_csv, 1946, 2025, conflict_types=[2], intensity_min=1)

    print(f"\nHand-curated interstate (1816-2003): {int(hc_inter.sum())}")
    print(f"COW v4 interstate (1816-2003): {int(cow_inter.sum())}")
    print(f"UCDP interstate (1946-2023): {int(ucdp_war.sum())}")

    # ---- Figure ----
    fig, axes = plt.subplots(3, 1, figsize=(14, 11))

    # Quakes panel — USGS vs NGDC 1900+ overlap
    ax = axes[0]
    yrs_modern = np.arange(1900, 2026)
    ax.bar(yrs_modern, usgs_m7.loc[1900:2025].reindex(yrs_modern, fill_value=0),
            color="#3355aa", alpha=0.75, label="USGS M≥7 (full)")
    ax.bar(yrs_modern, noaa_m7.reindex(yrs_modern, fill_value=0),
            color="#cc4422", alpha=0.5, label="NGDC M≥7 'significant' subset")
    ax.set_ylabel("M≥7 quakes/yr")
    ax.set_xlim(1900, 2030)
    ax.set_title("Quake catalogs (1900–2005 overlap): NGDC 'significant' subset is a strict subset of USGS")
    ax.legend(loc="upper right", fontsize=9)

    # Then a separate panel for NGDC pre-1900 extension
    ax_inset = ax.inset_axes([0.02, 0.55, 0.4, 0.4])
    pre1900 = noaa_m7.loc[-2150:1899]
    # Bin by century for visibility
    cent = (pre1900.index // 100) * 100
    cent_counts = pre1900.groupby(cent).sum()
    ax_inset.bar(cent_counts.index, cent_counts.values, width=80, color="#cc4422", alpha=0.85)
    ax_inset.set_title("NGDC M≥7 pre-1900 (per century, BCE→1900)", fontsize=9)
    ax_inset.set_xlabel("Century start", fontsize=8)

    # Volcanoes panel
    ax = axes[1]
    yrs_v = np.arange(1500, 2026)
    ax.bar(yrs_v, hc_volc_5.reindex(yrs_v, fill_value=0),
            color="#aa5522", alpha=0.85, label=f"Hand-curated VEI≥5: {int(hc_volc_5.sum())} since 1500")
    ax.bar(yrs_v, noaa_volc_deadly.reindex(yrs_v, fill_value=0),
            color="#3355aa", alpha=0.5, label=f"NGDC ≥100-death volcanoes: {int(noaa_volc_deadly.sum())} since 1500")
    ax.set_ylabel("Events/yr")
    ax.set_title("Volcanoes (1500-2025): hand-curated VEI≥5 vs NGDC ≥100-death events")
    ax.set_xlim(1500, 2030)
    ax.legend(loc="upper left", fontsize=9)

    # Wars panel
    ax = axes[2]
    yrs_w = np.arange(1816, 2026)
    ax.bar(yrs_w - 0.2, hc_inter.reindex(yrs_w, fill_value=0).values, width=0.4,
            color="#666666", alpha=0.85, label=f"Hand-curated interstate: {int(hc_inter.sum())} since 1816")
    ax.bar(yrs_w + 0.2, cow_inter.reindex(yrs_w, fill_value=0).values, width=0.4,
            color="#3355aa", alpha=0.85, label=f"COW v4 interstate: {int(cow_inter.sum())} since 1816")
    # UCDP overlay
    ucdp_modern = ucdp_war.reindex(yrs_w, fill_value=0)
    ax.plot(yrs_w, ucdp_modern.values / 10, color="#cc4422", linewidth=1.4,
            label=f"UCDP interstate / 10 (for scale): {int(ucdp_war.sum())} conflict-yrs since 1946")
    ax.set_ylabel("War onsets / year")
    ax.set_xlabel("Year")
    ax.set_xlim(1816, 2030)
    ax.set_title("Interstate war catalogs: hand-curated vs COW v4 (1816-2003) vs UCDP (1946-2023)")
    ax.legend(loc="upper right", fontsize=9)

    plt.tight_layout()
    plt.savefig(out / "31_canonical_compare.png", dpi=120)
    plt.close()
    print(f"\nWrote {out/'31_canonical_compare.png'}")


if __name__ == "__main__":
    main()
