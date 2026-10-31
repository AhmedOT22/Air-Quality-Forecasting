"""Archived, lead-specific forecasts and live weather context at Toronto Pearson."""
import json
from pathlib import Path
from urllib.parse import urlencode
import numpy as np
import pandas as pd
from data_sources import download

VARIABLES = {'temperature_c':'temperature_2m', 'humidity_pct':'relative_humidity_2m',
             'wind_speed_kmh':'wind_speed_10m', 'pressure_kpa':'surface_pressure'}


def url(start, end, previous=False):
    variables = [f'{name}_previous_day{h}' for h in range(1,8) for name in VARIABLES.values()] if previous else list(VARIABLES.values())
    host = 'previous-runs-api' if previous else 'api'
    return f'https://{host}.open-meteo.com/v1/forecast?' + urlencode({'latitude':43.67667,
        'longitude':-79.63056,'start_date':str(start),'end_date':str(end),
        'hourly':','.join(variables),'timezone':'Etc/GMT+5','wind_speed_unit':'kmh'})


def daily(payload, horizon=None):
    if payload.get('error') or payload.get('utc_offset_seconds') != -18000:
        raise ValueError('Weather API error or unexpected timezone')
    hourly = pd.DataFrame(payload['hourly'])
    hourly.index = pd.DatetimeIndex(pd.to_datetime(hourly.pop('time')), name='time_est')
    if hourly.index.has_duplicates or not hourly.index.is_monotonic_increasing:
        raise ValueError('Duplicate or unordered forecast weather timestamps')
    suffix = f'_previous_day{horizon}' if horizon else ''
    columns = [v+suffix for v in VARIABLES.values()]
    units = payload['hourly_units']
    if [units.get(c) for c in columns] != ['°C','%','km/h','hPa']:
        raise ValueError('Unexpected forecast weather units')
    result = pd.DataFrame(index=pd.date_range(hourly.index.min().normalize(), hourly.index.max().normalize(),name='Date'))
    for field, variable in VARIABLES.items():
        values = pd.to_numeric(hourly[variable+suffix],errors='raise')
        if np.isinf(values).any(): raise ValueError('Infinite weather forecast')
        stats = values.groupby(values.index.normalize()).agg(['mean','count'])
        result[field] = stats['mean'].where(stats['count'] >= 18)
    result.pressure_kpa /= 10
    return result


def archive(end='2026-09-30', raw='data/raw/forecast_weather'):
    tables=[]; sources=[]
    for year in range(2024,pd.Timestamp(end).year+1):
        stop = min(pd.Timestamp(end),pd.Timestamp(f'{year}-12-31')).date()
        content, record = download(url(f'{year}-01-01',stop,True),Path(raw)/f'previous_{year}_{stop}.json')
        payload=json.loads(content); sources.append(record)
        for h in range(1,8):
            d=daily(payload,h).reset_index();d['horizon']=h;tables.append(d)
    return pd.concat(tables,ignore_index=True),sources


def current(start,end,raw='data/raw/forecast_weather'):
    content,record=download(url(start,end),Path(raw)/f'live_{start}_{end}.json',refresh=True)
    return daily(json.loads(content)),record
