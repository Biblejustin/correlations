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
    load_yearly_famine_deaths_wpf,
    load_yearly_ucdp_conflicts,
    load_yearly_drought_intensity,
    load_yearly_terrorism_deaths,
    load_yearly_stock_crashes,
    load_yearly_noaa_quakes,
)
from detection_regimes import REGIMES, piecewise_detrend
from periodogram_extended import raw_periodogram, bootstrap_null

warnings.filterwarnings("ignore")

LOG = Path("PREDICTIONS_LOG.md")
RNG = np.random.default_rng(42)


def slope_per_decade(series: pd.Series, n_boot=2000):
    y = series.dropna().astype(float)
    x = y.index.values.astype(float)
    v = y.values
    a, _ = np.polyfit(x, v, 1)
    slopes = []
    n = len(x)
    for _ in range(n_boot):
        idx = RNG.integers(0, n, size=n)
        try:
            ai, _ = np.polyfit(x[idx], v[idx], 1)
            slopes.append(ai)
        except Exception:
            continue
    lo, hi = np.percentile(slopes, [2.5, 97.5])
    return a * 10, lo * 10, hi * 10


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
    ap.add_argument("--dry-run", action="store_true", help="print only, no log append")
    args = ap.parse_args()

    lines: list[str] = []
    today = datetime.date.today().isoformat()
    lines.append(f"## Scorecard {today}")
    lines.append("")
    lines.append("| Prediction | Current value | Threshold | Status |")
    lines.append("|---|---|---|---|")

    # ---- P8: wars×famines regime-detrended r stays >= +0.30 ----
    wars = np.log10(load_yearly_war_deaths_active(args.wars_csv, 1900, 2025) + 1)
    fam = np.log10(load_yearly_famine_deaths_wpf(args.famines_wpf_csv, 1900, 2025) + 1)
    wars_d = piecewise_detrend(wars.astype(float), REGIMES["wars_global"])
    fam_d = piecewise_detrend(fam.astype(float), REGIMES["famines"])
    mask = ~(wars_d.isna() | fam_d.isna())
    r, p = stats.pearsonr(wars_d[mask], fam_d[mask])
    lines.append(f"| P8 wars×famines detrended r | {r:+.3f} (p={p:.2g}) "
                  f"| ≥ +0.30 | {verdict(r >= 0.30)} |")

    # ---- P9b: Granger wars→famines significant at lags 1,2,5; reverse NS ----
    try:
        import contextlib
        import io
        from statsmodels.tsa.stattools import grangercausalitytests
        aligned = pd.DataFrame({"fam": fam_d[mask], "wars": wars_d[mask]}).dropna()
        with contextlib.redirect_stdout(io.StringIO()):
            fwd = grangercausalitytests(aligned[["fam", "wars"]], maxlag=5)
            rev = grangercausalitytests(aligned[["wars", "fam"]], maxlag=5)
        fwd_p = {lag: res[0]["ssr_ftest"][1] for lag, res in fwd.items()}
        rev_p = {lag: res[0]["ssr_ftest"][1] for lag, res in rev.items()}
        fwd_ok = all(fwd_p[lag] < 0.05 for lag in (1, 2, 5))
        rev_ok = all(pv > 0.05 for pv in rev_p.values())
        lines.append(f"| P9b Granger wars→famines p@1/2/5 "
                      f"| {fwd_p[1]:.3f}/{fwd_p[2]:.3f}/{fwd_p[5]:.3f} "
                      f"(reverse min {min(rev_p.values()):.2f}) "
                      f"| all <0.05, reverse NS | {verdict(fwd_ok and rev_ok)} |")
    except Exception as e:
        lines.append(f"| P9b Granger | error: {e} | | — |")

    # ---- P9c: intrastate (ethnos) conflict-years rising, CI excludes 0 ----
    intra = load_yearly_ucdp_conflicts(args.ucdp_csv, 1946, 2025,
                                         conflict_types=[3, 4])
    s, lo, hi = slope_per_decade(intra, args.n_boot)
    lines.append(f"| P9c UCDP intrastate trend | {s:+.2f}/dec [{lo:+.2f}, {hi:+.2f}] "
                  f"| positive, CI excludes 0 | {verdict(lo > 0)} |")

    # ---- P9d: interstate (basileia) flat or turning positive ----
    inter = load_yearly_ucdp_conflicts(args.ucdp_csv, 1946, 2025,
                                         conflict_types=[2])
    s2, lo2, hi2 = slope_per_decade(inter, args.n_boot)
    basileia_state = ("rising (CI excludes 0)" if lo2 > 0
                       else "flat (CI crosses 0)" if hi2 > 0 >= lo2
                       else "declining (CI excludes 0)")
    lines.append(f"| P9d UCDP interstate trend | {s2:+.3f}/dec [{lo2:+.3f}, {hi2:+.3f}] "
                  f"| flat now; rising = strongest confirmation | {basileia_state} |")

    # ---- P10: drought 11y periodogram peak stays significant ----
    dr = np.log10(load_yearly_drought_intensity(args.droughts_csv, 1850, 2025) + 1)
    v = dr.dropna().values
    freqs, power = raw_periodogram(v)
    null = bootstrap_null(v, n_boot=args.n_boot)
    f, pw, nl = freqs[1:], power[1:], null[1:]
    per = 1.0 / f
    band = (per >= 9) & (per <= 13)
    ratio = float(np.max((pw / np.maximum(nl, 1e-10))[band]))
    peak_per = float(per[band][np.argmax((pw / np.maximum(nl, 1e-10))[band])])
    lines.append(f"| P10 drought 11y peak | {ratio:.2f}× null at {peak_per:.1f}y "
                  f"| ≥ 1.0× | {verdict(ratio >= 1.0)} |")

    # ---- P12: terrorism deaths trend (1998+) stays positive ----
    terr = load_yearly_terrorism_deaths(args.terrorism_csv, 1998, 2025,
                                          log10_transform=True)
    terr = terr[terr.index <= 2021]  # GTD frozen at 2021
    s3, lo3, hi3 = slope_per_decade(terr, args.n_boot)
    pct = s3 * 100 * np.log(10)
    lines.append(f"| P12 terrorism deaths trend 1998–2021 | {pct:+.1f}%/dec "
                  f"| positive at p<0.05 | {verdict(lo3 > 0)} |")

    # ---- P12b: stock crashes stay at ~2/decade, not 3+ ----
    crashes = load_yearly_stock_crashes(args.crashes_csv, 1900, 2025,
                                          drawdown_min=20.0)
    last10 = int(crashes[crashes.index > crashes.index.max() - 10].sum())
    lines.append(f"| P12b crashes ≥20% in trailing 10y | {last10} "
                  f"| ≤ 2 (historical rate) | {verdict(last10 <= 2)} |")

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
