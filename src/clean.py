"""Cleaning functions shared by the ETL and by the data-quality checks.

Kept separate from etl_load.py so they can be unit-tested / dry-run without
needing a live Oracle connection (see src/dry_run_clean.py).
"""
from __future__ import annotations

import pandas as pd


def normalize_source(series: pd.Series) -> pd.Series:
    """Fix the case/whitespace defects the generator injects into utm_source.
    'GOOGLE', ' google', 'Google ' all become 'google' so they match channel_mapping.
    """
    return series.astype(str).str.strip().str.lower()


def map_channel(series_norm: pd.Series, chan_map: pd.DataFrame) -> pd.DataFrame:
    """Left-join normalized utm_source onto config/channel_mapping.csv.
    Unmapped values fall back to the 'other' row so nothing is silently dropped.
    """
    m = chan_map.set_index("source_raw")
    fallback = m.loc["other"]
    out = series_norm.to_frame("source_norm").join(m, on="source_norm")
    for col in ["channel_name", "channel_group", "is_paid", "utm_medium"]:
        out[col] = out[col].fillna(fallback[col])
    return out


def clean_campaign_id(series: pd.Series) -> pd.Series:
    """Blank / NaN utm_campaign on an otherwise-paid lead -> explicit '(unmapped)'
    rather than NULL, so a missing campaign is a visible, countable data-quality
    issue instead of silently vanishing into a foreign-key NULL.
    Handles NA explicitly: pandas' string dtype does NOT stringify NaN to 'nan'
    the way plain object dtype used to, so a .astype(str)-then-match-'nan' trick
    silently fails on newer pandas.
    """
    is_blank = series.isna()
    s = series.astype(str).str.strip()
    is_blank = is_blank | (s == "")
    s = s.mask(is_blank, "(unmapped)")
    return s


def dedupe_exact(df: pd.DataFrame, subset=None) -> tuple[pd.DataFrame, int]:
    before = len(df)
    out = df.drop_duplicates(subset=subset, keep="first")
    return out, before - len(out)


def clean_specialization(series: pd.Series) -> pd.Series:
    """Kaggle's placeholder 'Select' means the dropdown was left untouched -> treat as unknown."""
    s = series.astype(str).str.strip()
    s = s.replace({"Select": "Unspecified", "nan": "Unspecified", "": "Unspecified"})
    return s
