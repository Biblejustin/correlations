"""Predeclared historical climate-control sensitivity; no causal attribution.

Both fits use the same longest contiguous finite sample. The baseline uses
shared time/regime nuisance terms, so it is not a replication of the original
matrix's separately detrended correlations. Climate adjustment adds annual RNI
(monthly Relative Nino3.4, all 12 January--December months) and DMI. Seasonal
RONI must not be substituted for monthly RNI or averaged across calendar years.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

from detection_regimes import REGIMES
from monitoring.feeds import CONFIG
from statistical_helpers import bh_adjust, contiguous_overlap, last_complete_year

GLOBAL_MIN_YEARS = 20
REGIONAL_MIN_YEARS = 12
MIN_RESIDUAL_DF = 8
HAC_MAXLAGS = 3
FDR_ALPHA = 0.05
MAX_CONDITION_NUMBER = 1e10
FITS = ("baseline_time_regime", "climate_adjusted")
REGIONAL_COUNTRIES = ("ISR", "PSE", "LBN", "UKR", "SDN", "ETH", "SOM", "YEM")
REGIONAL_LAGS = (0, 1, 2)
GLOBAL_SERIES_SPEC = (
    ("M>=7 quakes", "quakes_m7"),
    ("War deaths log10", "wars_global"),
    ("Famine deaths log10 (WPF)", "famines"),
    ("Flood deaths log10", "floods"),
    ("Pandemic deaths log10", "pandemics"),
    ("Volcanoes VEI>=5", "volcanoes"),
    ("Cyclone deaths log10", "cyclones"),
    ("X1+ flares", "flares_x"),
    ("Terrorism deaths log10", "terrorism"),
    ("Stock crash intensity log10", "stock_crashes"),
)
REGIONAL_PAIRS = (
    ("conflict_total_deaths_per_100k", "refugees_origin_stock_change"),
    ("conflict_total_deaths_per_100k", "ipc_current_3plus_fraction"),
    ("retail_staple_price_yoy_pct", "ipc_current_3plus_fraction"),
)


def validate_plan():
    """Fail visibly if runtime defaults drift from the recorded analysis rules."""
    path = Path(__file__).with_name("extension_plan.json")
    raw = path.read_bytes()
    plan = json.loads(raw)["climate"]
    expected = {"annual_controls": ["rni", "dmi"], "fits": list(FITS),
                "global_minimum_years": GLOBAL_MIN_YEARS,
                "regional_minimum_years": REGIONAL_MIN_YEARS,
                "minimum_residual_degrees_of_freedom": MIN_RESIDUAL_DF,
                "hac_maxlags": HAC_MAXLAGS, "fdr_alpha": FDR_ALPHA}
    changed = [key for key, value in expected.items() if plan.get(key) != value]
    if changed:
        raise ValueError(f"Recorded climate plan/runtime mismatch: {', '.join(changed)}")
    return hashlib.sha256(raw).hexdigest()


def _annual_series(series, label):
    result = pd.Series(series, copy=True, dtype=float)
    if not result.index.is_unique:
        raise ValueError(f"{label}: duplicate annual years")
    years = np.asarray(result.index, dtype=float)
    if not np.isfinite(years).all() or not np.equal(years, np.floor(years)).all():
        raise ValueError(f"{label}: annual years must be finite integers")
    result.index = years.astype(int)
    return result.sort_index().replace([np.inf, -np.inf], np.nan)


def _climate_frame(annual_climate, end_year):
    if not {"year", "rni", "dmi"}.issubset(annual_climate.columns):
        raise ValueError("Climate input requires year, rni, dmi; seasonal roni is not annual rni")
    frame = annual_climate.set_index("year")
    frame = pd.DataFrame({name: _annual_series(frame[name], name) for name in ("rni", "dmi")})
    return frame.loc[(frame.index >= 1950) & (frame.index <= end_year)]


def paired_sample(x, y, annual_climate, *, lag=0, end_year=None):
    """Align x[t-lag], y[t], climate[t] and climate[t-lag] before either fit.

    Missing years split runs; ties choose the earliest run. An empty frame
    means no joint finite observation. Invalid schemas raise, never disappear.
    Caller supplies covered annual observations, with unknown years as NaN.
    """
    if lag not in (0, 1, 2):
        raise ValueError("Only predeclared lags 0, 1, 2 are supported")
    end_year = min(last_complete_year(), end_year if end_year is not None else last_complete_year())
    climate = _climate_frame(annual_climate, end_year)
    x, y = _annual_series(x, "predictor"), _annual_series(y, "response")
    x.index = x.index + lag
    columns = {"x": x, "y": y,
               "rni_response": climate.rni, "dmi_response": climate.dmi}
    if lag:
        for name in ("rni", "dmi"):
            shifted = climate[name].copy()
            shifted.index = shifted.index + lag
            columns[f"{name}_predictor"] = shifted
    frame = pd.DataFrame(columns)
    frame = frame.loc[(frame.index >= 1950 + lag) & (frame.index <= end_year)]
    if frame.empty or not np.isfinite(frame.to_numpy()).all(axis=1).any():
        return frame.iloc[:0]
    return contiguous_overlap(frame.to_dict("series"), min_years=1)


def _time_controls(years, breakpoints):
    """Shared union of fixed catalog regimes; segments under 3 years get means.

    Every occupied segment gets its own intercept and, with >=3 observations,
    centered trend, matching the existing piecewise detrending segment rule.
    No breakpoints are searched or selected using these data.
    """
    years = np.asarray(years, dtype=int)
    groups = np.searchsorted(sorted(set(breakpoints)), years, side="right")
    columns, names = [], []
    for group in np.unique(groups):
        mask = groups == group
        start, stop = years[mask].min(), years[mask].max()
        columns.append(mask.astype(float))
        names.append(f"intercept_{start}_{stop}")
        if mask.sum() >= 3:
            columns.append(np.where(mask, years - years[mask].mean(), 0.0))
            names.append(f"time_{start}_{stop}")
    return np.column_stack(columns), names


def _fit(frame, controls, names, *, fit, minimum_years, transform):
    row = {"fit": fit, "n": len(frame), "minimum_years": minimum_years,
           "control_columns": ";".join(names), "n_controls": len(names),
           "rank": None, "df_resid": None, "status": "unavailable",
           "reason": "", "partial_r": np.nan, "beta": np.nan,
           "beta_ci_low": np.nan, "beta_ci_high": np.nan, "p_hac": np.nan}
    if len(frame) < minimum_years:
        row["reason"] = "insufficient_contiguous_years"
        return row
    x, y = frame.x.to_numpy(), frame.y.to_numpy()
    if transform == "signed_log1p":
        x, y = np.sign(x) * np.log1p(abs(x)), np.sign(y) * np.log1p(abs(y))
    x_sd, y_sd = x.std(), y.std()
    if min(x_sd, y_sd) <= 1e-12:
        row["reason"] = "constant_series"
        return row
    # Scaling changes no nuisance span or tested coefficient's native units.
    xz, yz = (x - x.mean()) / x_sd, (y - y.mean()) / y_sd
    scale = np.sqrt(np.mean(controls ** 2, axis=0))
    if np.any(scale <= 1e-12):
        row["reason"] = "singular_controls"
        return row
    controls = controls / scale
    if np.linalg.matrix_rank(controls) != controls.shape[1]:
        row["reason"] = "singular_controls"
        return row
    rx = xz - controls @ np.linalg.lstsq(controls, xz, rcond=None)[0]
    ry = yz - controls @ np.linalg.lstsq(controls, yz, rcond=None)[0]
    if min(rx.std(), ry.std()) <= 1e-10:
        row["reason"] = "constant_after_controls"
        return row
    design = np.column_stack([controls, xz])
    rank = np.linalg.matrix_rank(design)
    row.update(rank=int(rank), df_resid=int(len(frame) - rank))
    if rank != design.shape[1] or np.linalg.cond(design) > MAX_CONDITION_NUMBER:
        row["reason"] = "singular_or_ill_conditioned_design"
        return row
    if row["df_resid"] < MIN_RESIDUAL_DF:
        row["reason"] = "insufficient_residual_degrees_of_freedom"
        return row
    result = sm.OLS(yz, design).fit(
        cov_type="HAC", cov_kwds={"maxlags": HAC_MAXLAGS, "use_correction": True}, use_t=True)
    if np.std(result.resid) <= 1e-10:
        row["reason"] = "zero_model_residual_variance"
        return row
    low, high = result.conf_int(alpha=FDR_ALPHA)[-1] * y_sd / x_sd
    pvalue, beta = float(result.pvalues[-1]), float(result.params[-1] * y_sd / x_sd)
    if not np.isfinite([pvalue, beta, low, high, result.bse[-1]]).all() or result.bse[-1] <= 0:
        row["reason"] = "invalid_hac_covariance"
        return row
    row.update(status="eligible", reason="", partial_r=float(np.corrcoef(rx, ry)[0, 1]),
               beta=beta, beta_ci_low=float(low), beta_ci_high=float(high), p_hac=pvalue)
    return row


def _pair_rows(x, y, climate, *, breaks, minimum_years, transform, identity, end_year):
    frame = paired_sample(x, y, climate, lag=identity["lag_years"], end_year=end_year)
    years = list(map(int, frame.index))
    sample = {"sample_years": ";".join(map(str, years)),
              "response_start_year": years[0] if years else None,
              "response_end_year": years[-1] if years else None,
              "predictor_start_year": years[0] - identity["lag_years"] if years else None,
              "predictor_end_year": years[-1] - identity["lag_years"] if years else None,
              "sample_sha256": hashlib.sha256(frame.to_csv(float_format="%.17g").encode()).hexdigest(),
              "transform": transform, "regime_breakpoints": ";".join(map(str, sorted(set(breaks))))}
    if years:
        baseline, baseline_names = _time_controls(frame.index, breaks)
    else:
        baseline, baseline_names = np.empty((0, 0)), []
    climate_names = [name for name in frame.columns if name not in ("x", "y")]
    adjusted = np.column_stack([baseline, frame[climate_names].to_numpy()])
    return [{**identity, **sample, **_fit(frame, controls, names, fit=fit,
                                       minimum_years=minimum_years, transform=transform)}
            for fit, controls, names in ((FITS[0], baseline, baseline_names),
                                         (FITS[1], adjusted, baseline_names + climate_names))]


def _finish(rows, family, *, end_year, minimum_years):
    table = pd.DataFrame(rows)
    # A missing test occupies its planned slot. Both fits share this correction.
    table["q_family"] = bh_adjust(table.p_hac.fillna(1.0).to_numpy())
    table["family_size"] = len(table)
    table["reject_fdr"] = table.status.eq("eligible") & table.q_family.lt(FDR_ALPHA)
    table.attrs["metadata"] = {
        "method_version": "historical_climate_controls_v1", "family": family,
        "extension_plan_sha256": validate_plan(),
        "family_size": len(table), "fits": list(FITS), "minimum_years": minimum_years,
        "minimum_residual_df": MIN_RESIDUAL_DF, "hac_maxlags": HAC_MAXLAGS,
        "hac_kernel": "Bartlett", "hac_finite_sample_correction": True,
        "inference": "OLS slope; HAC covariance; Student t with n minus full design rank df",
        "fdr": "BH across all pairs/lags and both fits; unavailable tests occupy p=1 slots",
        "fdr_alpha": FDR_ALPHA, "end_year": min(last_complete_year(), end_year or last_complete_year()),
        "sample": "Identical longest contiguous finite overlap for both fits; ties choose earliest",
        "climate": "rni: mean of 12 closed Jan-Dec monthly Relative Nino3.4 values; dmi: 12-month Jan-Dec mean",
        "lag_controls": "Response-year climate plus predictor-year climate for positive lags",
        "baseline": "Shared fixed time/regime nuisance basis; not replication of separately detrended original results",
        "interpretation": "Historical association sensitivity; no causal, prospective, or prophetic attribution",
        "family_separation": "Global and regional panels have distinct pre-existing hypotheses and observation units; no pooled significance claim",
        "confidence_intervals": "95% pointwise HAC slope intervals; not simultaneous or selection-adjusted",
    }
    return table


def global_climate_sensitivity(series_dict, annual_climate, *, end_year=None):
    """Existing 45 fixed matrix pairs, two fits each (90-test BH family).

    Values are existing loader outputs in their original count/log10 units.
    Mapping values may be a Series or (Series, expected regime key). Missing
    fixed keys stay unavailable; unknown names or altered regimes are errors.
    """
    validate_plan()
    unknown = set(series_dict) - dict(GLOBAL_SERIES_SPEC).keys()
    if unknown:
        raise ValueError(f"Unknown global series outside fixed family: {sorted(unknown)}")
    sources = {}
    for name, regime in GLOBAL_SERIES_SPEC:
        value = series_dict.get(name, pd.Series(dtype=float))
        if isinstance(value, tuple):
            value, supplied_regime = value
            if supplied_regime != regime:
                raise ValueError(f"Changed fixed regime for {name}")
        sources[name] = value
    rows = []
    for (predictor, regime_x), (response, regime_y) in itertools.combinations(GLOBAL_SERIES_SPEC, 2):
        identity = {"family": "global", "pair_id": f"{regime_x}__{regime_y}", "country": "global",
                    "predictor": predictor, "response": response, "lag_years": 0}
        rows.extend(_pair_rows(sources[predictor], sources[response], annual_climate,
                               breaks=REGIMES[regime_x] + REGIMES[regime_y],
                               minimum_years=GLOBAL_MIN_YEARS, transform="existing_loader_units",
                               identity=identity, end_year=end_year))
    return _finish(rows, "global", end_year=end_year, minimum_years=GLOBAL_MIN_YEARS)


def _regional_series(panel, country, metric):
    subset = panel.loc[panel.country.eq(country) & panel.metric.eq(metric)].copy()
    if metric == "ipc_current_3plus_fraction":
        # Preserve the upstream assessed-geography gate even for direct callers.
        scope = subset.get("geographic_scope", pd.Series("", index=subset.index))
        subset.loc[~scope.eq("verified comparable assessment geography"), "value"] = np.nan
    if metric == "conflict_total_deaths_per_100k":
        if country == "ISR":
            subset["value"] = np.nan
        elif country == "SDN":
            subset.loc[subset.year.lt(2012), "value"] = np.nan
    return _annual_series(subset.set_index("year").value, f"{country}/{metric}")


def regional_climate_sensitivity(panel, annual_climate, *, config=CONFIG, end_year=None):
    """Existing country/pair/lag cells, signed log1p and unchanged geography gates.

    Default: 8 countries x 3 pairs x 3 lags x 2 fits = 144 tests. Inputs must be
    the existing coverage/geography-gated annual panel, not raw observations.
    """
    validate_plan()
    countries, lags = list(config["countries"]), list(config["annual_lags"])
    if (tuple(countries) != REGIONAL_COUNTRIES or tuple(lags) != REGIONAL_LAGS
            or config["minimum_test_years"] != REGIONAL_MIN_YEARS):
        raise ValueError("Country/lag cells must match the existing fixed 72-cell family")
    minimum = REGIONAL_MIN_YEARS
    rows = []
    for country, (predictor, response), lag in itertools.product(countries, REGIONAL_PAIRS, lags):
        identity = {"family": "regional", "pair_id": f"{country}__{predictor}__{response}__lag{lag}",
                    "country": country, "predictor": predictor, "response": response, "lag_years": lag}
        rows.extend(_pair_rows(_regional_series(panel, country, predictor),
                               _regional_series(panel, country, response), annual_climate,
                               breaks=[], minimum_years=minimum, transform="signed_log1p",
                               identity=identity, end_year=end_year))
    return _finish(rows, "regional", end_year=end_year, minimum_years=minimum)


def report_lines(global_table, regional_table):
    lines = ["Historical climate-control sensitivity uses paired samples and fixed hypotheses.",
             "Baseline fits remove shared time/regime terms; adjusted fits also remove annual monthly-RNI and DMI terms.",
             "Seasonal RONI is a separate monitor and is not used in these calendar-year fits."]
    for label, table in (("Global", global_table), ("Regional", regional_table)):
        lines.append(f"{label}: {len(table)} planned tests across both fits; "
                     f"{table.status.eq('eligible').sum()} eligible, {table.reject_fdr.sum()} BH q<0.05.")
        reasons = table.loc[table.status.ne("eligible"), "reason"].value_counts()
        if len(reasons):
            lines.append("Unavailable: " + "; ".join(f"{key}={value}" for key, value in reasons.items()) + ".")
    lines.extend(["BH families are separate for the pre-existing global and regional panels; unavailable tests remain in each family.",
                  "Slope confidence intervals are pointwise. Climate adjustment does not establish causation, forecasting skill, or prophetic significance."])
    return lines


def write_outputs(global_table, regional_table, output_dir):
    """Write separate sensitivity artifacts; never overwrite frozen study results."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for label, table in (("global", global_table), ("regional", regional_table)):
        stem = output_dir / f"{label}_climate_sensitivity"
        csv_path, json_path = stem.with_suffix(".csv"), stem.with_suffix(".json")
        table.to_csv(csv_path, index=False)
        json_path.write_text(table.to_json(orient="records", indent=2) + "\n")
        paths.extend([csv_path, json_path])
    metadata_path = output_dir / "climate_controls_metadata.json"
    metadata_path.write_text(json.dumps({"global": global_table.attrs["metadata"],
                                         "regional": regional_table.attrs["metadata"]}, indent=2, allow_nan=False) + "\n")
    report_path = output_dir / "climate_controls_report.md"
    report_path.write_text("\n\n".join(report_lines(global_table, regional_table)) + "\n")
    return paths + [metadata_path, report_path]
