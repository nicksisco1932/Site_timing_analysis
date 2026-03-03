#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
tulsa_timebase.py  (v0.1)
-------------------------

Canonical helpers for working with TULSA time data from local.db
and downstream CSVs.

Goals
-----
- Single point of truth for parsing ISO-like local timestamps, e.g.,
      '2021-08-05 07:16:50.6126507'
- Optional timezone localization.
- Reusable utilities for computing per-case relative times.

These helpers are intended to be imported by:
    - tulsa_state_machine.py
    - tulsa_time_sanity.py
    - any future scripts that need clean datetime handling.
"""

from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd


def parse_time_column(
    df: pd.DataFrame,
    source_col: str = "TimeStamp",
    target_col: str = "ts",
    tz: Optional[str] = None,
    drop_bad: bool = True,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Parse an ISO-like local datetime column into a pandas datetime column.

    Parameters
    ----------
    df : DataFrame
        Input dataframe.
    source_col : str
        Name of the column with string timestamps (e.g., 'TimeStamp').
    target_col : str
        Name of the datetime column to create (e.g., 'ts').
    tz : str or None
        If provided, naive datetimes are interpreted as local in this timezone
        using tz-localize. If None, datetimes remain naive.
    drop_bad : bool
        If True, rows where parsing fails are dropped.
    verbose : bool
        If True, print a warning if any rows fail to parse.

    Returns
    -------
    DataFrame
        Dataframe with a new datetime column `target_col`.
    """
    if source_col not in df.columns:
        raise ValueError(f"parse_time_column: '{source_col}' not found in dataframe.")

    out = df.copy()

    out[target_col] = pd.to_datetime(out[source_col], errors="coerce")

    n_bad = out[target_col].isna().sum()
    if n_bad > 0 and verbose:
        print(
            f"[tulsa_timebase] WARNING: {n_bad} rows had unparseable "
            f"{source_col} values; {'dropping' if drop_bad else 'keeping as NaT'}."
        )

    if drop_bad:
        out = out.dropna(subset=[target_col])

    if tz is not None:
        # Interpret as local time, *not* "convert from UTC".
        out[target_col] = out[target_col].dt.tz_localize(tz)

    return out


def add_relative_times(
    df: pd.DataFrame,
    ts_col: str = "ts",
    group_col: str | Iterable[str] = "PtId",
    start_col: str = "start_sec",
    dur_col: str = "duration_sec",
) -> pd.DataFrame:
    """
    Given an absolute timestamp column, compute per-case relative start/duration.

    Parameters
    ----------
    df : DataFrame
        Dataframe that already has a datetime column `ts_col`.
    ts_col : str
        Name of the datetime column (e.g., 'ts').
    group_col : str or list of str
        Column(s) that define a "case" (e.g., 'Pt', 'PtId').
    start_col : str
        Name for the relative-start column (seconds from first event).
    dur_col : str
        Name for the duration column (seconds to next event).

    Returns
    -------
    DataFrame
        Dataframe with `start_col` and `dur_col` added.
    """
    if ts_col not in df.columns:
        raise ValueError(f"add_relative_times: '{ts_col}' not found in dataframe.")

    out = df.copy()

    # Normalize group_col to a list
    if isinstance(group_col, (list, tuple)):
        group_keys = list(group_col)
    else:
        group_keys = [group_col]

    # If any of the group keys are missing, treat entire DF as one group
    if not all(k in out.columns for k in group_keys):
        group_keys = None

    if group_keys is None:
        out = out.sort_values(ts_col)
        out[start_col] = (out[ts_col] - out[ts_col].min()).dt.total_seconds()
        out[dur_col] = out[start_col].shift(-1) - out[start_col]
    else:
        out = out.sort_values(group_keys + [ts_col])
        out[start_col] = (
            out.groupby(group_keys)[ts_col]
               .transform(lambda s: (s - s.min()).dt.total_seconds())
        )
        out[dur_col] = (
            out.groupby(group_keys)[start_col].shift(-1) - out[start_col]
        )

    out[dur_col] = out[dur_col].fillna(0).clip(lower=0)
    return out
