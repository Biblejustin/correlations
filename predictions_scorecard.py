"""
Live scorecard for the pre-registered predictions in PREDICTIONS.md.

PREDICTIONS.md is frozen (that's the point of pre-registration). This script
recomputes the measurable inputs behind the trackable predictions on current
data and appends a dated entry to PREDICTIONS_LOG.md, so the 2030/2035/2040
revisits become a running record instead of a one-shot archaeology project.

Covered predictions (the ones computable from yearly series without a full
pipeline run): P8 wars×famines coupling, P9b Granger direction, P9c/P9d
ethnos vs basileia trends, P10 drought 11-year peak, P12 terrorism trend,
P12b stock-crash rate, P14 NGDC M≥7 trend. Contraction predictions (P1-P3)
depend on `contractions_analysis.py` output and future data; run that
separately.
"""
import argparse
import datetime
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from correlate_events import (
    load_yearly_war_deaths_active,
    load_yearly_war_deaths_split,
    load_yearly_famine_deaths_wpf,
    load_yearly_ucdp_conflicts,
    load_yearly_drought_affected,
    load_yearly_terrorism_deaths,
    load_yearly_stock_crashes,
    load_yearly_noaa_quakes,
)
from detection_regimes import REGIMES, piecewise_detrend
from periodogram_extended import spectral_inference
from statistical_helpers import contiguous_overlap, residual_slope_ci, last_complete_year
from granger import granger_family


LOG = Path("PREDICTIONS_LOG.md")
RNG = np.random.default_rng(42)


def slope_per_decade(series: pd.Series, n_boot=2000):
    try:
        y = contiguous_overlap({"value": series}).value
    except ValueError:
        return np.nan, np.nan, np.nan
    return tuple(v * 10 for v in residual_slope_ci(y.index.to_numpy(), y.to_numpy(), n_boot))


def verdict(ok: bool | None) -> str:
    if ok is None:
        return "—"
    return "on track" if ok else "OFF TRACK"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wars-csv", default="data/wars.csv")
    ap.add_argument("--famines-wpf-csv", default="data/famine_deaths_by_year.csv")
    ap.add_argument("--ucdp-csv", default="data/ucdp_prio_conflicts.csv")
    ap.add_argument("--droughts-csv", default="data/droughts.csv")
    ap.add_argument("--terrorism-csv", default="data/terrorism.csv")
    ap.add_argument("--crashes-csv", default="data/stock_crashes.csv")
    ap.add_argument("--noaa-quakes-csv", default="data/noaa_significant_earthquakes.csv")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--year-hi", type=int, default=last_complete_year())
    ap.add_argument("--dry-run", action="store_true", help="print only, no log append")
    args = ap.parse_args()

    lines: list[str] = []
    today = datetime.date.today().isoformat()
    lines.append(f"## Scorecard {today}")
    lines.append("Method audit v2: complete observed years; corrected temporal intervals, full Granger family, AR(1) band-search null. PREDICTIONS.md remains frozen. Corrected diagnostics are not the original preregistered tests.")
    lines.append("")
    lines.append("| Prediction | Current value | Threshold | Status |")
    lines.append("|---|---|---|---|")

    # ---- P8: wars×famines regime-detrended r stays >= +0.30 ----
    wars = np.log10(load_yearly_war_deaths_active(args.wars_csv, 1900, args.year_hi) + 1)
    fam = np.log10(load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, args.year_hi) + 1)
    wars_d = piecewise_detrend(wars.astype(float), REGIMES["wars_global"])
    fam_d = piecewise_detrend(fam.astype(float), REGIMES["famines"])
    mask = ~(wars_d.isna() | fam_d.isna())
    r, p = stats.pearsonr(wars_d[mask], fam_d[mask])
    lines.append(f"| P8 wars×famines detrended r | {r:+.3f} (descriptive Pearson r) "
                  f"| ≥ +0.30 | {verdict(r >= 0.30)} |")

    # P9b: retain raw values, report corrected full six-direction family.
    try:
        wi = np.log10(load_yearly_war_deaths_split(args.wars_csv, "interstate", 1900, args.year_hi) + 1)
        wn = np.log10(load_yearly_war_deaths_split(args.wars_csv, "intrastate", 1900, args.year_hi) + 1)
        family = granger_family(wars_d, piecewise_detrend(wi, REGIMES["wars_global"]),
                                piecewise_detrend(wn, REGIMES["wars_global"]), fam_d)
        forward = family[family.direction == "Wars (combined) → Famines"].set_index("lag_order")
        p_text = "/".join(f"{forward.loc[k, 'p']:.3f}" for k in (1, 2, 5))
        q_text = "/".join(f"{forward.loc[k, 'q']:.3f}" for k in (1, 2, 5))
        lines.append(f"| P9b Granger audit, model orders 1/2/5 | raw p {p_text}; full-family q {q_text} "
                     f"| 30-test family, q<0.05 | {int(family.fdr_significant.sum())} corrected survivors; exploratory |")
    except (ValueError, np.linalg.LinAlgError) as exc:
        lines.append(f"| P9b Granger | unavailable: {exc} | | — |")

    # ---- P9c: intrastate (ethnos) conflict-years rising, CI excludes 0 ----
    intra = load_yearly_ucdp_conflicts(args.ucdp_csv, 1946, args.year_hi,
                                         conflict_types=[3, 4])
    s, lo, hi = slope_per_decade(intra, args.n_boot)
    lines.append(f"| P9c UCDP intrastate trend | {s:+.2f}/dec [{lo:+.2f}, {hi:+.2f}] "
                  f"| positive, CI excludes 0 | {verdict(lo > 0)} |")

    # ---- P9d: interstate (basileia) flat or turning positive ----
    inter = load_yearly_ucdp_conflicts(args.ucdp_csv, 1946, args.year_hi,
                                         conflict_types=[2])
    s2, lo2, hi2 = slope_per_decade(inter, args.n_boot)
    basileia_state = ("rising (CI excludes 0)" if lo2 > 0
                       else "flat (CI crosses 0)" if hi2 > 0 >= lo2
                       else "declining (CI excludes 0)")
    lines.append(f"| P9d UCDP interstate trend | {s2:+.3f}/dec [{lo2:+.3f}, {hi2:+.3f}] "
                  f"| flat now; rising = strongest confirmation | {basileia_state} |")

    # P10 corrected diagnostic; frozen original white-noise ratio not reused.
    dr = np.log10(load_yearly_drought_affected(args.droughts_csv, 1850, args.year_hi) + 1)
    try:
        observed = contiguous_overlap({"value": dr}, min_years=20).value
        spectral = spectral_inference(observed.to_numpy(), n_boot=args.n_boot)
        lines.append(f"| P10 drought affected-allocation proxy, method v2 | AR(1) band-search p={spectral['band_p']:.3f}, "
                     f"peak {spectral['peak_period']:.1f}y | single prespecified 9–13y band | "
                     "corrected diagnostic; no physical drought or solar attribution |")
    except ValueError as exc:
        lines.append(f"| P10 drought allocation proxy | unavailable: {exc} | | — |")

    # ---- P12: terrorism deaths trend (1998+) stays positive ----
    terr = load_yearly_terrorism_deaths(args.terrorism_csv, 1998, args.year_hi,
                                          log10_transform=True)
    terr = terr[terr.index <= 2021]  # GTD frozen at 2021
    s3, lo3, hi3 = slope_per_decade(terr, args.n_boot)
    pct = s3 * 100 * np.log(10)
    lines.append(f"| P12 terrorism deaths trend 1998–2021 | {pct:+.1f}%/dec "
                  f"| positive at p<0.05 | {verdict(lo3 > 0)} |")

    # ---- P12b: stock crashes stay at ~2/decade, not 3+ ----
    crashes = load_yearly_stock_crashes(args.crashes_csv, 1900, args.year_hi,
                                          drawdown_min=20.0)
    trailing = crashes.reindex(range(args.year_hi - 9, args.year_hi + 1))
    if trailing.notna().all():
        last10 = int(trailing.sum())
        lines.append(f"| P12b crashes ≥20% in trailing 10y | {last10} "
                     f"| ≤ 2 (historical rate) | {verdict(last10 <= 2)} |")
    else:
        lines.append(f"| P12b crashes ≥20% in trailing 10y | incomplete coverage ({int(trailing.notna().sum())}/10 years) | ≤ 2 | — |")

    # ---- P14: NGDC M≥7 trend still declining/flat (1900-2005 window) ----
    ngdc = load_yearly_noaa_quakes(args.noaa_quakes_csv, 1900, 2005, mag_min=7.0)
    s4, lo4, hi4 = slope_per_decade(ngdc, args.n_boot)
    lines.append(f"| P14 NGDC M≥7 trend 1900–2005 | {s4:+.2f}/dec [{lo4:+.2f}, {hi4:+.2f}] "
                  f"| declining or flat (reversal ⇒ real intensification) "
                  f"| {verdict(lo4 <= 0)} |")

    lines.append("")
    report = "\n".join(lines)
    print(report)

    if not args.dry_run:
        header = ("# Predictions scorecard log\n\n"
                   "Appended by `predictions_scorecard.py` on each data refresh. "
                   "PREDICTIONS.md itself stays frozen (pre-registered "
                   "2026-05-20); this file tracks how the measurable inputs "
                   "evolve between the 2030/2035/2040 revisits.\n\n")
        if LOG.exists():
            LOG.write_text(LOG.read_text() + report + "\n")
        else:
            LOG.write_text(header + report + "\n")
        print(f"Appended to {LOG}")


if __name__ == "__main__":
    main()
