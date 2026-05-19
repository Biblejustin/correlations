"""
Shared helpers for event-vs-earthquake-vs-flare correlation tests.

Each topic script (wars.py, famines.py, israel.py) imports these.

Tests:
  - yearly_corr(): Pearson + Spearman on yearly counts, raw and regime-detrended
  - lag_corr():    lag scan -10..+10 years on detrended residuals
  - window_test(): for each event year, does the year fall in a high-quake or
                   high-flare year window? Compared to chance via binomial.
  - event_day_window(): for date-precise events (Israel modern dates), does
                        the day fall near an M>=7 quake or X1+ flare?
"""
from __future__ import annotations
import sqlite3
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from detection_regimes import REGIMES, piecewise_detrend


# ---------- Data loaders ----------

def load_yearly_quakes_m7(eq_db_1900: str, year_lo=1900, year_hi=2025) -> pd.Series:
    """Yearly M>=7 quake counts from extended USGS catalog."""
    con = sqlite3.connect(eq_db_1900)
    q = pd.read_sql("SELECT time_ms, mag FROM quakes WHERE mag>=7", con)
    q["year"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.year
    s = q.groupby("year").size().reindex(range(year_lo, year_hi + 1), fill_value=0)
    s.name = "m7_count"
    return s


def load_yearly_quakes_m8(eq_db_1900: str, year_lo=1900, year_hi=2025) -> pd.Series:
    con = sqlite3.connect(eq_db_1900)
    q = pd.read_sql("SELECT time_ms, mag FROM quakes WHERE mag>=8", con)
    q["year"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.year
    s = q.groupby("year").size().reindex(range(year_lo, year_hi + 1), fill_value=0)
    s.name = "m8_count"
    return s


def load_yearly_flares_x1(flares_csv: str, year_lo=1976, year_hi=2025) -> pd.Series:
    """Yearly X1+ flare counts."""
    df = pd.read_csv(flares_csv, parse_dates=["date"])
    df["year"] = df["date"].dt.year
    s = df.groupby("year").size().reindex(range(year_lo, year_hi + 1), fill_value=0)
    s.name = "xflare_count"
    return s


def load_yearly_wars(wars_csv: str, year_lo=1400, year_hi=2025,
                     include_ongoing: bool = True) -> pd.Series:
    """Yearly count of war ONSETS (groupby start_year)."""
    df = pd.read_csv(wars_csv)
    s = df.groupby("start_year").size().reindex(range(year_lo, year_hi + 1), fill_value=0)
    s.name = "war_starts"
    return s


def load_yearly_war_deaths_active(wars_csv: str, year_lo=1400, year_hi=2025,
                                   log10_transform: bool = False) -> pd.Series:
    """
    Yearly war deaths attributed to ACTIVE years: each war contributes
    deaths_estimate / duration_years to every year it was active
    [start_year, end_year] inclusive.

    If log10_transform=True, returns log10(deaths + 1) per year.
    """
    df = pd.read_csv(wars_csv)
    years = range(year_lo, year_hi + 1)
    out = pd.Series(0.0, index=years, name="war_deaths_active")
    for _, row in df.iterrows():
        s = int(row["start_year"]); e = int(row["end_year"])
        if e < year_lo or s > year_hi:
            continue
        s = max(s, year_lo); e = min(e, year_hi)
        duration = e - s + 1
        per_year = float(row["deaths_estimate"]) / duration
        for y in range(s, e + 1):
            out.loc[y] += per_year
    if log10_transform:
        out = np.log10(out + 1.0)
        out.name = "log10_war_deaths"
    return out


def load_yearly_famines(famines_csv: str, year_lo=1500, year_hi=2025) -> pd.Series:
    df = pd.read_csv(famines_csv)
    s = df.groupby("start_year").size().reindex(range(year_lo, year_hi + 1), fill_value=0)
    s.name = "famine_starts"
    return s


def load_yearly_famine_deaths_active(famines_csv: str, year_lo=1500, year_hi=2025,
                                      log10_transform: bool = False) -> pd.Series:
    """Same spreading logic as wars."""
    df = pd.read_csv(famines_csv)
    years = range(year_lo, year_hi + 1)
    out = pd.Series(0.0, index=years, name="famine_deaths_active")
    for _, row in df.iterrows():
        s = int(row["start_year"]); e = int(row["end_year"])
        if e < year_lo or s > year_hi:
            continue
        s = max(s, year_lo); e = min(e, year_hi)
        duration = e - s + 1
        per_year = float(row["deaths_estimate"]) / duration
        for y in range(s, e + 1):
            out.loc[y] += per_year
    if log10_transform:
        out = np.log10(out + 1.0)
        out.name = "log10_famine_deaths"
    return out


def load_yearly_famine_deaths_wpf(deaths_by_year_csv: str, year_lo=1870, year_hi=2025,
                                    log10_transform: bool = False) -> pd.Series:
    """
    Authoritative WPF/OWID yearly famine deaths.

    The deaths-by-region-year.csv (from Biblejustin/famines-tracking) has
    annual famine deaths already attributed to specific years by region.
    Sum across regions to get global yearly famine deaths.
    """
    df = pd.read_csv(deaths_by_year_csv)
    df = df[~df["entity"].str.startswith("World", na=False)]  # avoid double-counting
    yearly = df.groupby("year")["famine_deaths"].sum()
    s = yearly.reindex(range(year_lo, year_hi + 1), fill_value=0).astype(float)
    if log10_transform:
        s = np.log10(s + 1.0)
        s.name = "log10_wpf_famine_deaths"
    else:
        s.name = "wpf_famine_deaths"
    return s


# ---------- Flood data loaders ----------

def load_yearly_flood_events(floods_csv: str, year_lo=1900, year_hi=2025,
                              deaths_min: float = 0,
                              dedupe_match_groups: bool = True) -> pd.Series:
    """
    Yearly flood event counts. By default, deaths_min=0 returns all events
    (very detection-bias-sensitive). Use deaths_min=1000 for the detection-
    clean band.

    dedupe_match_groups: if True, when EM-DAT and Dartmouth record the same
    event (match_group_id matches), count once.
    """
    df = pd.read_csv(floods_csv, low_memory=False)
    df["year"] = pd.to_datetime(df["start_date"], errors="coerce").dt.year
    df["deaths"] = pd.to_numeric(df["deaths"], errors="coerce").fillna(0)

    if dedupe_match_groups and "match_group_id" in df.columns:
        # Keep one row per match_group_id; for unmatched (NaN), keep all
        with_group = df[df["match_group_id"].notna()].drop_duplicates(subset=["match_group_id"])
        without_group = df[df["match_group_id"].isna()]
        df = pd.concat([with_group, without_group], ignore_index=True)

    if deaths_min > 0:
        df = df[df["deaths"] >= deaths_min]

    s = df.groupby("year").size().reindex(range(year_lo, year_hi + 1), fill_value=0)
    s.name = f"flood_events_deaths_ge_{int(deaths_min)}"
    return s


def load_yearly_flood_deaths(floods_csv: str, year_lo=1900, year_hi=2025,
                              log10_transform: bool = False,
                              dedupe_match_groups: bool = True) -> pd.Series:
    """Yearly total flood deaths, spread across active days (start_date..end_date)."""
    df = pd.read_csv(floods_csv, low_memory=False)
    df["start"] = pd.to_datetime(df["start_date"], errors="coerce")
    df["end"] = pd.to_datetime(df["end_date"], errors="coerce")
    df["end"] = df["end"].fillna(df["start"])
    df["deaths"] = pd.to_numeric(df["deaths"], errors="coerce").fillna(0)
    df = df.dropna(subset=["start"])

    if dedupe_match_groups and "match_group_id" in df.columns:
        with_group = df[df["match_group_id"].notna()].drop_duplicates(subset=["match_group_id"])
        without_group = df[df["match_group_id"].isna()]
        df = pd.concat([with_group, without_group], ignore_index=True)

    years = range(year_lo, year_hi + 1)
    out = pd.Series(0.0, index=years, name="flood_deaths_active")
    for _, row in df.iterrows():
        s = row["start"].year; e = row["end"].year
        if e < year_lo or s > year_hi or row["deaths"] == 0:
            continue
        s = max(s, year_lo); e = min(e, year_hi)
        duration = e - s + 1
        per_year = float(row["deaths"]) / duration
        for y in range(s, e + 1):
            out.loc[y] += per_year
    if log10_transform:
        out = np.log10(out + 1.0)
        out.name = "log10_flood_deaths"
    return out


def load_flood_event_dates(floods_csv: str, deaths_min: float = 1000,
                            exclude_tsunami: bool = True):
    """Date-precise flood event starts (for daily-window tests).

    exclude_tsunami=True (default) drops events where `cause` matches tsunami
    or tidal surge — these are quake-caused and would contaminate any
    earthquake-flood window test (reverse causation).
    """
    df = pd.read_csv(floods_csv, low_memory=False)
    df["start"] = pd.to_datetime(df["start_date"], errors="coerce")
    df["deaths"] = pd.to_numeric(df["deaths"], errors="coerce").fillna(0)
    df = df.dropna(subset=["start"])
    df = df[df["deaths"] >= deaths_min]
    if exclude_tsunami and "cause" in df.columns:
        mask = df["cause"].astype(str).str.contains("tsunami|tidal", case=False, na=False)
        df = df[~mask]
    if "match_group_id" in df.columns:
        with_group = df[df["match_group_id"].notna()].drop_duplicates(subset=["match_group_id"])
        without_group = df[df["match_group_id"].isna()]
        df = pd.concat([with_group, without_group], ignore_index=True)
    return df["start"].dt.normalize().tolist()


def load_levant_quakes(eq_db_modern: str, lat=31.78, lon=35.21, radius_km=500,
                        mag_min=4.0):
    """Load modern Levant quakes from USGS M>=4 1965+ catalog (spatial filter)."""
    con = sqlite3.connect(eq_db_modern)
    q = pd.read_sql(f"SELECT time_ms, mag, lat, lon FROM quakes WHERE mag>={mag_min}", con)
    # Approximate flat-earth distance — fine at this scale
    dlat = q["lat"] - lat
    dlon = (q["lon"] - lon) * np.cos(np.deg2rad(lat))
    dist_km = np.sqrt(dlat**2 + dlon**2) * 111.0
    q = q[dist_km <= radius_km].copy()
    q["date"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.tz_localize(None)
    return q


def load_modern_quakes_dates(eq_db_modern: str, mag_min=7.0):
    con = sqlite3.connect(eq_db_modern)
    q = pd.read_sql(f"SELECT time_ms, mag FROM quakes WHERE mag>={mag_min}", con)
    q["date"] = pd.to_datetime(q["time_ms"], unit="ms", utc=True).dt.tz_localize(None)
    return q


def load_flare_dates(flares_csv: str):
    return pd.read_csv(flares_csv, parse_dates=["date"])


def load_israel_dates(israel_json: str):
    with open(israel_json) as f:
        return json.load(f)


# ---------- Core tests ----------

def yearly_corr(a: pd.Series, b: pd.Series, regime_key_a: str = None,
                regime_key_b: str = None) -> dict:
    """
    Pearson + Spearman on overlap years. Returns raw + per-regime-detrended.
    Detrending uses REGIMES[regime_key] for each series.
    """
    overlap = a.index.intersection(b.index)
    a2 = a.loc[overlap].astype(float)
    b2 = b.loc[overlap].astype(float)
    mask = ~(a2.isna() | b2.isna())
    a2 = a2[mask]; b2 = b2[mask]

    out = {"n": int(mask.sum())}
    if len(a2) < 3:
        return out | {"raw_r": float("nan"), "raw_p": float("nan"),
                      "det_r": float("nan"), "det_p": float("nan")}
    r, p = stats.pearsonr(a2, b2)
    rs, ps = stats.spearmanr(a2, b2)
    out |= {"raw_r": r, "raw_p": p, "raw_rho": rs, "raw_p_spear": ps}

    if regime_key_a and regime_key_b:
        ad = piecewise_detrend(a2, REGIMES.get(regime_key_a, []))
        bd = piecewise_detrend(b2, REGIMES.get(regime_key_b, []))
        m2 = ~(ad.isna() | bd.isna())
        if m2.sum() >= 3:
            r2, p2 = stats.pearsonr(ad[m2], bd[m2])
            out |= {"det_r": r2, "det_p": p2}
        else:
            out |= {"det_r": float("nan"), "det_p": float("nan")}
    return out


def lag_corr(a: pd.Series, b: pd.Series, lags: range,
             regime_key_a: str = None, regime_key_b: str = None) -> pd.DataFrame:
    """Lag-correlation on regime-detrended residuals.
    Positive lag = b leads a by lag years (i.e. correlate a with b shifted forward)."""
    overlap = a.index.intersection(b.index)
    a2 = a.loc[overlap].astype(float)
    b2 = b.loc[overlap].astype(float)
    if regime_key_a:
        a2 = piecewise_detrend(a2, REGIMES.get(regime_key_a, []))
    if regime_key_b:
        b2 = piecewise_detrend(b2, REGIMES.get(regime_key_b, []))

    rows = []
    for lag in lags:
        bs = b2.shift(lag)
        mask = ~(a2.isna() | bs.isna())
        if mask.sum() < 5:
            rows.append({"lag": lag, "r": float("nan"), "p": float("nan"),
                         "n": int(mask.sum())})
            continue
        r, p = stats.pearsonr(a2[mask], bs[mask])
        rows.append({"lag": lag, "r": r, "p": p, "n": int(mask.sum())})
    return pd.DataFrame(rows)


def event_window_test(event_dates: list, target_dates: list,
                      window_days: int, all_dates: set) -> dict:
    """
    For a set of point events, count how many fall within +/- window_days
    of any target date. Compare to chance via binomial.

    `all_dates` is the population of valid days (e.g. all days in the modern
    quake catalog window). `target_dates` is the set of target events
    (e.g. M>=7 quakes or X1+ flares).
    """
    target_set = set(pd.to_datetime(target_dates).normalize())
    # build the "near a target" window
    near = set()
    for d in target_set:
        for k in range(-window_days, window_days + 1):
            near.add(d + pd.Timedelta(days=k))
    near &= all_dates
    n_total = len(all_dates)
    n_near = len(near)
    events = [pd.Timestamp(d).normalize() for d in event_dates if pd.Timestamp(d).normalize() in all_dates]
    n_events = len(events)
    if n_events == 0 or n_total == 0:
        return {"n_events": n_events, "n_near": n_near, "n_total": n_total,
                "observed_in_window": 0, "expected": 0,
                "ratio": float("nan"), "p_two_sided": float("nan")}
    observed = sum(1 for d in events if d in near)
    expected = n_events * n_near / n_total
    p = stats.binomtest(observed, n=n_events, p=n_near / n_total,
                        alternative="two-sided").pvalue
    return {
        "n_events": n_events, "n_target": len(target_set),
        "n_near": n_near, "n_total": n_total,
        "window_days": window_days,
        "observed_in_window": observed,
        "expected": expected,
        "ratio": observed / expected if expected else float("nan"),
        "p_two_sided": p,
    }
