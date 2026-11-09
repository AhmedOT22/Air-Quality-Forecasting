"""Shared data loading and leakage-aware feature construction for 1–7 day forecasts."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from data_sources import WEATHER_FIELDS

LAGS = (0, 1, 2, 6, 13)


def target_spec(frame):
    if 'AQI' in frame:
        return 'AQI', 'AQI points', 1
    if 'PM25' in frame:
        return 'PM25', 'µg/m³', 0
    raise ValueError('Expected AQI, or PM25 for the separate concentration analysis')


def seasonal_lag(step, delay):
    # Repeat the most recently AVAILABLE week. With delayed AQI, target-7
    # can still be unavailable at horizon 7, so repeat the earlier week.
    return delay + 6 - ((step + delay - 1) % 7)


def validate_frame(frame):
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is not None:
        raise ValueError('Expected timezone-free daily calendar dates')
    if (frame.empty or frame.index.hasnans or frame.index.has_duplicates
            or not frame.index.is_monotonic_increasing
            or not frame.index.equals(frame.index.normalize())):
        raise ValueError('Dates must be nonempty, sorted, and unique')
    if not frame.index.equals(pd.date_range(frame.index[0], frame.index[-1], freq='D', name=frame.index.name)):
        raise ValueError('Retain every calendar day, including missing target days')
    target, _, _ = target_spec(frame)
    if target == 'AQI' and 'aqi_standard' in frame and frame.aqi_standard.nunique(dropna=False) != 1:
        raise ValueError('AQI breakpoint definitions must be consistent throughout the series')
    values = pd.to_numeric(frame[target], errors='raise')
    if np.isinf(values).any() or (values.dropna() < 0).any() or values.notna().sum() < 60:
        raise ValueError('Need at least 60 finite, non-negative observed target days; gaps may be NaN')
    for name in WEATHER_FIELDS:
        if name not in frame or np.isinf(pd.to_numeric(frame[name], errors='raise')).any():
            raise ValueError(f'Missing or infinite weather feature: {name}')
    for name in ('naps_station_id', 'climate_station_id'):
        if name in frame and (frame[name].isna().any() or frame[name].nunique() != 1):
            raise ValueError('A benchmark must contain one station pair, not mixed stations')
    return frame


def load_data(path):
    path = Path(path)
    manifest_path = path.with_suffix('.manifest.json')
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['prepared_sha256']:
            raise ValueError('Prepared data checksum differs from source manifest')
    frame = pd.read_csv(path, dtype={'naps_station_id': str, 'climate_station_id': str})
    if 'Date' not in frame:
        raise ValueError('CSV must contain Date')
    dates = pd.to_datetime(frame.pop('Date'), format='%Y-%m-%d', errors='raise')
    frame.index = pd.DatetimeIndex(dates, name='Date')
    return validate_frame(frame)


def make_features(frame, horizon):
    """Rows describe information available after the completed origin day only."""
    if not 1 <= horizon <= 7:
        raise ValueError('Supported horizons are 1 through 7 days')
    target, _, delay = target_spec(frame)
    available = frame[target].shift(delay)
    features = pd.DataFrame(index=frame.index)
    for lag in LAGS:
        features[f'{target.lower()}_lag_{lag}'] = available.shift(lag)
    features[f'{target.lower()}_mean_7d'] = available.rolling(7, min_periods=7).mean()
    target_dates = frame.index + pd.Timedelta(days=horizon)
    angle = 2 * np.pi * target_dates.dayofyear / 365.25
    features['target_day_sin'] = np.sin(angle)
    features['target_day_cos'] = np.cos(angle)
    lag_columns = features.columns.tolist()
    for name in WEATHER_FIELDS:
        features[name] = frame[name]  # completed origin day, never target-day weather
    # All pollution features must be observed; targets are never filled. Training-
    # only median imputation is reserved for missing weather predictors.
    eligible = features[lag_columns].notna().all(axis=1)
    return features, lag_columns, eligible
