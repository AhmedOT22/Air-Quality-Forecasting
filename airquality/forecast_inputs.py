"""Forecast inputs for the day being predicted: weather by lead time and CAMS air quality.

Two public Open-Meteo products feed the models:

* **Weather forecasts by lead time** (Previous Runs API, from January 2024). For each
  target day it returns what the forecast issued 1 to 7 days earlier said, so a
  back-test uses the same information a real forecast had.
* **CAMS air-quality forecasts** (Air Quality API, from August 2022): modelled PM2.5,
  ozone and aerosol optical depth, which carry long-range smoke that no local
  reading can see. The archive holds only each run's first hours, so historical
  values are near-term quality at every lead. Back-tests with CAMS are therefore an
  upper bound; the live ledger stores real forecasts by lead to measure the truth.

Both archives are append-only CSV files under ``data/processed``: ``update`` fetches
only the days after the last stored date and records every download in a manifest.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd

from airquality.sources import download

# Pearson airport (weather) and the Toronto West monitor (air quality).
WEATHER_SITE = {"latitude": 43.67667, "longitude": -79.63056}
MONITOR_SITE = {"latitude": 43.709444, "longitude": -79.5435}
HORIZONS = range(1, 8)
CAMS_MAX_HORIZON = 5  # the CAMS global forecast reaches five days
MIN_HOURS = 18

VARIABLES = {
    "temperature_c": "temperature_2m",
    "humidity_pct": "relative_humidity_2m",
    "wind_speed_kmh": "wind_speed_10m",
    "pressure_kpa": "surface_pressure",
}
WEATHER_UNITS = ["°C", "%", "km/h", "hPa"]
CAMS_VARIABLES = {
    "pm2_5": "μg/m³",
    "ozone": "μg/m³",
    "aerosol_optical_depth": "",
}
CAMS_COLUMNS = ["cams_pm25", "cams_pm25_max", "cams_o3_max", "cams_aod"]

WEATHER_FILE = "forecast_weather.csv"
CAMS_FILE = "cams_daily.csv"
MANIFEST_FILE = "forecast_inputs.manifest.json"


def url(start, end, previous=False):
    variables = (
        [f"{name}_previous_day{h}" for h in HORIZONS for name in VARIABLES.values()]
        if previous
        else list(VARIABLES.values())
    )
    host = "previous-runs-api" if previous else "api"
    return f"https://{host}.open-meteo.com/v1/forecast?" + urlencode(
        {
            **WEATHER_SITE,
            "start_date": str(start),
            "end_date": str(end),
            "hourly": ",".join(variables),
            "timezone": "Etc/GMT+5",
            "wind_speed_unit": "kmh",
        }
    )


def cams_url(start=None, end=None, forecast_days=None):
    query = {
        **MONITOR_SITE,
        "hourly": ",".join(CAMS_VARIABLES),
        "timezone": "Etc/GMT+5",
    }
    if forecast_days:
        query["forecast_days"] = forecast_days
    else:
        query.update(start_date=str(start), end_date=str(end))
    return "https://air-quality-api.open-meteo.com/v1/air-quality?" + urlencode(query)


def _hourly(payload):
    if payload.get("error") or payload.get("utc_offset_seconds") != -18000:
        raise ValueError("Forecast API error or unexpected timezone")
    hourly = pd.DataFrame(payload["hourly"])
    hourly.index = pd.DatetimeIndex(pd.to_datetime(hourly.pop("time")), name="time_est")
    if hourly.index.has_duplicates or not hourly.index.is_monotonic_increasing:
        raise ValueError("Duplicate or unordered forecast timestamps")
    return hourly


def _calendar(hourly):
    return pd.date_range(
        hourly.index.min().normalize(), hourly.index.max().normalize(), name="Date"
    )


def _aggregate(values, how):
    values = pd.to_numeric(values, errors="raise")
    if np.isinf(values).any():
        raise ValueError("Infinite forecast value")
    stats = values.groupby(values.index.normalize()).agg([how, "count"])
    return stats[how].where(stats["count"] >= MIN_HOURS)


def daily(payload, horizon=None):
    """Daily means of the weather forecast issued ``horizon`` days before each date."""
    hourly = _hourly(payload)
    suffix = f"_previous_day{horizon}" if horizon else ""
    columns = [v + suffix for v in VARIABLES.values()]
    if [payload["hourly_units"].get(c) for c in columns] != WEATHER_UNITS:
        raise ValueError("Unexpected forecast weather units")
    result = pd.DataFrame(index=_calendar(hourly))
    for field, variable in VARIABLES.items():
        result[field] = _aggregate(hourly[variable + suffix], "mean")
    result.pressure_kpa /= 10
    return result


def cams_daily(payload):
    """Daily CAMS summaries: mean and peak PM2.5, peak ozone, mean aerosol depth."""
    hourly = _hourly(payload)
    units = payload["hourly_units"]
    if any(units.get(name) != unit for name, unit in CAMS_VARIABLES.items()):
        raise ValueError("Unexpected CAMS units")
    result = pd.DataFrame(index=_calendar(hourly))
    result["cams_pm25"] = _aggregate(hourly.pm2_5, "mean")
    result["cams_pm25_max"] = _aggregate(hourly.pm2_5, "max")
    result["cams_o3_max"] = _aggregate(hourly.ozone, "max")
    result["cams_aod"] = _aggregate(hourly.aerosol_optical_depth, "mean")
    return result


def weather_by_lead(payload):
    tables = []
    for h in HORIZONS:
        table = daily(payload, h).reset_index()
        table["horizon"] = h
        tables.append(table)
    return pd.concat(tables, ignore_index=True)


def read_weather(path):
    table = pd.read_csv(path, parse_dates=["Date"])
    if table.duplicated(["Date", "horizon"]).any():
        raise ValueError("Duplicate archived forecast dates")
    return table


def read_cams(path):
    table = pd.read_csv(path, parse_dates=["Date"]).set_index("Date")
    if table.index.has_duplicates:
        raise ValueError("Duplicate CAMS dates")
    return table


def _next_day(last, first):
    return pd.Timestamp(first) if last is None else last + pd.Timedelta(days=1)


def update(end, output="data/processed", raw="data/raw/forecast_inputs"):
    """Append days up to ``end`` to both archives; existing rows are never rewritten."""
    output, raw, end = Path(output), Path(raw), pd.Timestamp(end).normalize()
    manifest_path = output / MANIFEST_FILE
    manifest = (
        json.loads(manifest_path.read_text())
        if manifest_path.exists()
        else {"sources": []}
    )
    weather_path, cams_path = output / WEATHER_FILE, output / CAMS_FILE
    weather = read_weather(weather_path) if weather_path.exists() else None
    start = _next_day(None if weather is None else weather.Date.max(), "2024-01-01")
    while start <= end:  # one calendar year per request keeps each call small
        stop = min(end, pd.Timestamp(f"{start.year}-12-31"))
        content, record = download(
            url(start.date(), stop.date(), previous=True),
            raw / f"weather_{start.date()}_{stop.date()}.json",
        )
        new = weather_by_lead(json.loads(content))
        weather = new if weather is None else pd.concat([weather, new])
        manifest["sources"].append({"archive": WEATHER_FILE, **record})
        start = stop + pd.Timedelta(days=1)
    cams = read_cams(cams_path) if cams_path.exists() else None
    start = _next_day(None if cams is None else cams.index.max(), "2022-08-04")
    while start <= end:
        stop = min(end, pd.Timestamp(f"{start.year}-12-31"))
        content, record = download(
            cams_url(start.date(), stop.date()),
            raw / f"cams_{start.date()}_{stop.date()}.json",
        )
        new = cams_daily(json.loads(content))
        cams = new if cams is None else pd.concat([cams, new])
        manifest["sources"].append({"archive": CAMS_FILE, **record})
        start = stop + pd.Timedelta(days=1)
    weather = weather.sort_values(["horizon", "Date"]).reset_index(drop=True)
    weather.to_csv(weather_path, index=False, float_format="%.4f")
    cams.sort_index().to_csv(cams_path, float_format="%.4f")
    manifest.update(
        weather_end=str(weather.Date.max().date()),
        cams_end=str(cams.index.max().date()),
        weather_sha256=hashlib.sha256(weather_path.read_bytes()).hexdigest(),
        cams_sha256=hashlib.sha256(cams_path.read_bytes()).hexdigest(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        attribution="Weather and air-quality data by Open-Meteo.com (CC BY 4.0); "
        "air quality from CAMS (Copernicus Atmosphere Monitoring Service)",
        cams_caveat="Archived CAMS values are near-term forecasts at every lead; "
        "back-tests that use them are an upper bound on live skill",
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return weather, cams


class ForecastInputs:
    """Weather forecasts by lead and CAMS summaries, looked up by target date."""

    def __init__(self, weather, cams):
        self.weather = {
            int(h): table.drop(columns="horizon").set_index("Date")
            for h, table in weather.groupby("horizon")
        }
        self.cams = cams

    @classmethod
    def load(cls, folder="data/processed"):
        folder = Path(folder)
        return cls(read_weather(folder / WEATHER_FILE), read_cams(folder / CAMS_FILE))

    def weather_for(self, dates, horizon):
        return self.weather[horizon].reindex(dates)

    def cams_for(self, dates):
        return self.cams.reindex(dates)

    def with_live(self, origin, weather, cams):
        """Add the forecasts retrieved now for the days after ``origin``."""
        origin = pd.Timestamp(origin)
        updated = ForecastInputs.__new__(ForecastInputs)
        updated.weather = {}
        for h in HORIZONS:
            date = origin + pd.Timedelta(days=h)
            table = self.weather.get(h, pd.DataFrame(columns=list(VARIABLES)))
            if weather is not None and date in weather.index:
                table = pd.concat(
                    [table.drop(index=date, errors="ignore"), weather.loc[[date]]]
                )
            updated.weather[h] = table
        updated.cams = self.cams
        if cams is not None:
            future = cams.loc[cams.index > origin]
            updated.cams = pd.concat(
                [self.cams.drop(index=future.index, errors="ignore"), future]
            )
        return updated


def live_weather(start, end, raw="data/raw/forecast_inputs"):
    content, record = download(
        url(start, end), Path(raw) / f"live_weather_{start}_{end}.json", refresh=True
    )
    return daily(json.loads(content)), record


def live_cams(raw="data/raw/forecast_inputs", stamp=None):
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    content, record = download(
        cams_url(forecast_days=CAMS_MAX_HORIZON + 2),
        Path(raw) / f"live_cams_{stamp}.json",
        refresh=True,
    )
    return cams_daily(json.loads(content)), record
