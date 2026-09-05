"""Shared, deterministic time-series safeguards for exploratory monitoring."""
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


def last_complete_year():
    return datetime.now(ZoneInfo("America/Chicago")).year - 1


def bh_adjust(pvalues):
    """BH q-values over the full planned family, retaining missing tests as NaN."""
    p = np.asarray(pvalues, dtype=float)
    q = np.full(p.shape, np.nan)
    valid = np.flatnonzero(np.isfinite(p))
    if not len(valid):
        return q
    order = valid[np.argsort(p[valid])]
    adjusted = p[order] * p.size / np.arange(1, len(order) + 1)
    q[order] = np.minimum(1, np.minimum.accumulate(adjusted[::-1])[::-1])
    return q


def contiguous_overlap(series, min_years=8):
    """Select longest finite annual overlap; never compress a missing year.

    Ties select the earliest run. Source columns share exactly the same mask.
    Raises when no eligible run exists; callers must report an unavailable test.
    """
    frame = pd.DataFrame(series).sort_index().astype(float)
    if frame.empty or not frame.index.is_unique:
        raise ValueError("Annual series must have nonempty, unique year indices")
    years = np.asarray(frame.index, dtype=int)
    if not np.array_equal(years, np.asarray(frame.index)):
        raise ValueError("Annual indices must be integer years")
    frame = frame.reindex(range(int(years.min()), int(years.max()) + 1))
    mask = np.isfinite(frame.to_numpy()).all(axis=1)
    cuts = np.flatnonzero(np.diff(np.r_[False, mask, False]))
    runs = [(int(s), int(e)) for s, e in zip(cuts[::2], cuts[1::2])]
    start, end = max(runs, key=lambda pair: pair[1] - pair[0], default=(0, 0))
    if end - start < min_years:
        raise ValueError(f"Need {min_years} contiguous observed annual values; longest run={end-start}")
    return frame.iloc[start:end]


def block_indices(n, rng, block_length=None):
    """Circular moving blocks, default ceil(cuberoot(n)); caller owns RNG."""
    length = min(n, max(1, block_length or int(np.ceil(n ** (1 / 3)))))
    starts = rng.integers(0, n, int(np.ceil(n / length)))
    return ((starts[:, None] + np.arange(length)) % n).ravel()[:n]


def residual_slope_ci(x, y, n_boot=2000, seed=42):
    """Trend CI from fitted residual blocks; preserves estimated trend."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3 or not np.isfinite(x).all() or not np.isfinite(y).all() or np.ptp(x) == 0:
        return np.nan, np.nan, np.nan
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    residuals = y - fitted
    residuals -= residuals.mean()
    rng = np.random.default_rng(seed)
    slopes = [np.polyfit(x, fitted + residuals[block_indices(len(y), rng)], 1)[0]
              for _ in range(n_boot)]
    lo, hi = np.percentile(slopes, [2.5, 97.5])
    return float(slope), float(lo), float(hi)


def baseline_z_score(series, baseline=(1985, 2010), min_years=20):
    """Fixed historical reference; future values cannot change earlier scores."""
    s = series.astype(float).replace([np.inf, -np.inf], np.nan)
    ref = s.loc[(s.index >= baseline[0]) & (s.index <= baseline[1])].dropna()
    if len(ref) < min_years or ref.std(ddof=0) <= 0:
        return s * np.nan
    return (s - ref.mean()) / ref.std(ddof=0)


def indicator_domain(name):
    """Fixed v2 six-domain map. M8 is a sensitivity control, not another vote."""
    if name.startswith("M>=8"):
        return None
    if name.startswith(("M>=7", "VEI")):
        return "geophysical"
    if name.startswith("X1"):
        return "solar"
    if name.startswith(("Flood", "Cyclone", "Drought")):
        return "hydroclimate_impacts"
    if name.startswith("Pandemic"):
        return "health"
    if name.startswith(("Economic", "Stock")):
        return "economy"
    if name.startswith(("Interstate", "Intrastate", "Famine", "Refugees", "Coups", "Terrorism")):
        return "conflict_and_humanitarian_impacts"
    raise ValueError(f"No prespecified composite domain for {name!r}")


def domain_composite(indicators, years, baseline=(1985, 2010)):
    """Fixed member weights within domains, equal domain weights, full coverage.

    Returns standardized indicators, domain means, and coverage/score table.
    A missing member invalidates its domain; any missing domain invalidates
    the headline score. This is a descriptive mean, not a unit-normal z score.
    """
    z = pd.DataFrame({item[0]: baseline_z_score(item[1], baseline).reindex(years)
                      for item in indicators}, index=years)
    membership = {}
    for name in z:
        domain = indicator_domain(name)
        if domain is not None:
            membership.setdefault(domain, []).append(name)
    domains = pd.DataFrame({domain: z[names].mean(axis=1, skipna=False)
                            for domain, names in membership.items()}, index=years)
    eligible = domains.notna().all(axis=1)
    summary = pd.DataFrame({"composite": domains.mean(axis=1, skipna=False),
                            "eligible": eligible,
                            "observed_domains": domains.notna().sum(axis=1),
                            "required_domains": len(domains.columns),
                            "domains_above_1": (domains > 1).sum(axis=1).where(eligible)}, index=years)
    summary.index.name = "year"
    baseline_coverage = {}
    for item in indicators:
        name, source = item[:2]
        if indicator_domain(name) is None:
            continue
        ref = source.loc[(source.index >= baseline[0]) & (source.index <= baseline[1])].replace([np.inf, -np.inf], np.nan).dropna()
        reason = ("fewer than 20 observed baseline years" if len(ref) < 20 else
                  "constant baseline" if ref.std(ddof=0) <= 0 else None)
        baseline_coverage[name] = {"observed_years": len(ref), "required_years": 20,
                                   "status": reason or "eligible baseline",
                                   "observed_panel_years": int(z[name].notna().sum())}
    unavailable = [f"{name}: {info['status']} ({info['observed_years']} years)"
                   for name, info in baseline_coverage.items() if info["status"] != "eligible baseline"]
    reason = "; ".join(unavailable) if unavailable else "No year has all fixed members observed together"
    summary.attrs.update(version="domain_composite_v2", baseline=list(baseline),
                         membership=membership, eligibility="all fixed members in all domains",
                         baseline_coverage=baseline_coverage,
                         eligible_years=int(eligible.sum()),
                         unavailable_reason=reason if not eligible.any() else None,
                         interpretation="Descriptive equal-domain mean; no calibrated significance or unit-normal scale")
    return z, domains, summary
