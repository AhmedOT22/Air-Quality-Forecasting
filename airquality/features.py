"""Shared data loading and leakage-aware feature construction for 1–7 day forecasts."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from airquality.sources import WEATHER_FIELDS

LAGS = (0, 1, 2, 6, 13)


def target_spec(frame):
    if "AQI" in frame:
        return "AQI", "AQI points", 1
    if "PM25" in frame:
        return "PM25", "µg/m³", 0
    raise ValueError("Expected AQI, or PM25 for the separate concentration analysis")


def seasonal_lag(step, delay):
    # Repeat the most recently AVAILABLE week. With delayed AQI, target-7
    # can still be unavailable at horizon 7, so repeat the earlier week.
    return delay + 6 - ((step + delay - 1) % 7)


def validate_frame(frame):
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is not None:
        raise ValueError("Expected timezone-free daily calendar dates")
    if (
        frame.empty
        or frame.index.hasnans
        or frame.index.has_duplicates
        or not frame.index.is_monotonic_increasing
        or not frame.index.equals(frame.index.normalize())
    ):
        raise ValueError("Dates must be nonempty, sorted, and unique")
    if not frame.index.equals(
        pd.date_range(frame.index[0], frame.index[-1], freq="D", name=frame.index.name)
    ):
        raise ValueError("Retain every calendar day, including missing target days")
    target, _, _ = target_spec(frame)
    if (
        target == "AQI"
        and "aqi_standard" in frame
        and frame.aqi_standard.nunique(dropna=False) != 1
    ):
        raise ValueError(
            "AQI breakpoint definitions must be consistent throughout the series"
        )
    values = pd.to_numeric(frame[target], errors="raise")
    if (
        np.isinf(values).any()
        or (values.dropna() < 0).any()
        or values.notna().sum() < 60
    ):
        raise ValueError(
            "Need at least 60 finite, non-negative observed target days; gaps may be NaN"
        )
    for name in WEATHER_FIELDS:
        if (
            name not in frame
            or np.isinf(pd.to_numeric(frame[name], errors="raise")).any()
        ):
            raise ValueError(f"Missing or infinite weather feature: {name}")
    for name in ("naps_station_id", "climate_station_id"):
        if name in frame and (frame[name].isna().any() or frame[name].nunique() != 1):
            raise ValueError(
                "A benchmark must contain one station pair, not mixed stations"
            )
    return frame


def load_data(path):
    path = Path(path)
    manifest_path = path.with_suffix(".manifest.json")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["prepared_sha256"]:
            raise ValueError("Prepared data checksum differs from source manifest")
    frame = pd.read_csv(path, dtype={"naps_station_id": str, "climate_station_id": str})
    if "Date" not in frame:
        raise ValueError("CSV must contain Date")
    dates = pd.to_datetime(frame.pop("Date"), format="%Y-%m-%d", errors="raise")
    frame.index = pd.DatetimeIndex(dates, name="Date")
    return validate_frame(frame)


# Feature blocks. Each block lists inputs that are known when the forecast is issued.
FEATURE_SETS = {
    # AQI history, time of year and the origin day's weather (the original model).
    "history": ("history", "calendar", "weather"),
    # + the origin day's own pollutant readings, complete before the AQI is final.
    "same_day": ("history", "calendar", "weather", "same_day"),
    # + the weather forecast for the day being predicted.
    "forecast": ("history", "calendar", "weather", "same_day", "forecast_weather"),
    # + CAMS modelled PM2.5, ozone and aerosol for the day being predicted.
    "forecast_cams": (
        "history",
        "calendar",
        "weather",
        "same_day",
        "forecast_weather",
        "cams",
    ),
}
SAME_DAY = ("PM25_AQI", "PM25_max_1h", "O3_max_1h", "NO2_max_1h")
SAME_DAY_WINDOWS = ("PM25_evening", "O3_afternoon")
PREVIOUS_DAY = ("PM25_AQI", "O3_AQI", "NO2_AQI")
FORECAST_START = pd.Timestamp("2024-01-01")  # first day of the forecast-by-lead archive


def build_features(frame, horizon, feature_set="history", inputs=None, fit_end=None):
    """Features for forecasting ``horizon`` days after each origin day.

    Rows describe only information available once the origin day is complete.
    Returns the feature table, the columns that must be present, and a mask of
    usable origins.

    ``inputs`` (a ``ForecastInputs``) supplies forecasts for the target day. The
    forecast-by-lead archive starts in 2024; for earlier target days the observed
    weather stands in so the model can learn from the full history. That stand-in
    is applied only to target days on or before ``fit_end``, so it can enter
    training rows but never a row being evaluated or forecast.
    """
    if not 1 <= horizon <= 7:
        raise ValueError("Supported horizons are 1 through 7 days")
    blocks = FEATURE_SETS[feature_set]
    target, _, delay = target_spec(frame)
    prefix = target.lower()
    available = frame[target].shift(delay)
    features = pd.DataFrame(index=frame.index)
    for lag in LAGS:
        features[f"{prefix}_lag_{lag}"] = available.shift(lag)
    features[f"{prefix}_mean_7d"] = available.rolling(7, min_periods=7).mean()
    required = features.columns.tolist()
    target_dates = frame.index + pd.Timedelta(days=horizon)
    angle = 2 * np.pi * target_dates.dayofyear / 365.25
    features["target_day_sin"] = np.sin(angle)
    features["target_day_cos"] = np.cos(angle)
    lag_columns = features.columns.tolist()
    for name in WEATHER_FIELDS:
        features[name] = frame[name]  # completed origin day, never target-day weather
    if "same_day" in blocks:
        for name in (*SAME_DAY, *SAME_DAY_WINDOWS):
            features[f"{name}_origin"] = frame[name]
        for name in PREVIOUS_DAY:
            features[f"{name}_previous"] = frame[name].shift(1)
    if "forecast_weather" in blocks:
        if inputs is None:
            raise ValueError("Forecast features need forecast inputs")
        forecast = inputs.weather_for(target_dates, horizon)
        standin_end = FORECAST_START - pd.Timedelta(days=1)
        if fit_end is not None:
            standin_end = min(standin_end, pd.Timestamp(fit_end))
        use_observed = (
            target_dates <= standin_end
            if fit_end is not None
            else np.zeros(len(frame), dtype=bool)
        )
        for name in WEATHER_FIELDS:
            values = pd.Series(forecast[name].to_numpy(), index=frame.index)
            observed = pd.Series(
                frame[name].reindex(target_dates).to_numpy(), index=frame.index
            )
            column = f"forecast_{name}"
            features[column] = values.where(~use_observed, observed)
            required.append(column)
    if "cams" in blocks:
        if inputs is None:
            raise ValueError("CAMS features need forecast inputs")
        reach = horizon <= 5  # the CAMS forecast reaches five days
        cams = inputs.cams_for(target_dates)
        for name in cams:
            features[name] = cams[name].to_numpy() if reach else np.nan
        origin = inputs.cams_for(frame.index)["cams_pm25"].to_numpy()
        features["cams_pm25_origin"] = origin if reach else np.nan
    # All pollution history must be observed; targets are never filled. Other
    # gaps are left for the model (training-only median, or native handling).
    eligible = features[required].notna().all(axis=1)
    return features, lag_columns, eligible, required


def make_features(frame, horizon):
    """The original feature set: AQI history, time of year and origin-day weather."""
    features, lag_columns, eligible, _ = build_features(frame, horizon, "history")
    return features, lag_columns, eligible
