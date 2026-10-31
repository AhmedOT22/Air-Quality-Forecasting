"""Rebuild the original four-pollutant AQI objective from verified NAPS observations."""
import io
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from aqi import daily_aqi
from data_sources import DEFAULT_STATION, download, naps_url, prepare as prepare_pm25


def read_hourly(content, pollutant, station_id=DEFAULT_STATION):
    text = content.decode('utf-8-sig')
    expected = 'µg/m3' if pollutant == 'PM25' else 'ppb'
    if expected not in text[:1000] or 'hour ending local standard time' not in text[:1000]:
        raise ValueError('Unexpected pollutant units or timestamp convention')
    lines = text.splitlines()
    header = next((i for i, line in enumerate(lines) if 'NAPS ID//' in line), None)
    if header is None:
        raise ValueError('NAPS bilingual header missing')
    frame = pd.read_csv(io.StringIO('\n'.join(lines[header:])), dtype=str)
    frame.columns = [c.split('//')[0].strip() for c in frame.columns]
    frame['NAPS ID'] = frame['NAPS ID'].str.strip().str.zfill(6)
    if 'Method Code' not in frame:
        frame['Method Code'] = 'not supplied in gas export'
    frame = frame.loc[frame['NAPS ID'].eq(station_id)].copy()
    expected_name = 'PM2.5' if pollutant == 'PM25' else pollutant
    if frame.empty or not frame.Pollutant.eq(expected_name).all():
        raise ValueError(f'No {pollutant} at {station_id}')
    if frame.duplicated(['Date', 'Method Code']).any():
        raise ValueError('Duplicate station/method/date')
    coords = frame[['Latitude', 'Longitude']].drop_duplicates()
    if len(coords) != 1:
        raise ValueError('Station coordinates change within annual observations')
    frame['Date'] = pd.to_datetime(frame['Date'], format='%Y-%m-%d', errors='raise')
    if frame.Date.isna().any():
        raise ValueError('Missing pollutant date')
    hours = [f'H{h:02d}' for h in range(1, 25)]
    long = frame.melt(id_vars=['Date', 'Method Code'], value_vars=hours,
                      var_name='hour', value_name='value')
    long['value'] = pd.to_numeric(long.value, errors='raise')
    if np.isinf(long.value).any():
        raise ValueError('Infinite source reading')
    other_negative = int((long.value.lt(0) & long.value.ne(-999)).sum())
    valid = long.loc[long.value.ge(0)].copy()
    valid['timestamp'] = valid.Date + pd.to_timedelta(valid.hour.str[1:].astype(int) - 1, unit='h')
    if valid.timestamp.duplicated().any():
        raise ValueError('Overlapping valid method readings; source review required')
    index = pd.date_range(frame.Date.min(), frame.Date.max() + pd.Timedelta(hours=23), freq='h')
    series = valid.set_index('timestamp').value.reindex(index).rename(pollutant)
    report = {'pollutant': pollutant, 'units': expected,
              'methods': sorted(frame['Method Code'].unique()),
              'latitude': float(coords.Latitude.iloc[0]), 'longitude': float(coords.Longitude.iloc[0]),
              'valid_hours': int(series.notna().sum()), 'calendar_hours': len(series),
              'rejected_negative_hours_excluding_sentinel': other_negative}
    return series, report


def prepare_aqi(start_year=2020, end_year=2024, raw_dir='data/raw',
                output='data/processed/daily_aqi.csv', standard='epa_2018', refresh=False):
    raw = Path(raw_dir)
    weather, pm_manifest = prepare_pm25(start_year, end_year, raw_dir,
                                       'data/processed/daily_pm25.csv', refresh=refresh)
    annual, quality, sources = [], [], list(pm_manifest['sources'])
    for pollutant in ('PM25', 'O3', 'NO2', 'SO2'):
        years = []
        for year in range(start_year, end_year + 1):
            path = f'Data-Donnees/{year}/ContinuousData-DonneesContinu/HourlyData-DonneesHoraires/{pollutant}_{year}.csv'
            content, record = download(naps_url(path), raw / f'{pollutant}_{year}.csv',
                                       refresh=refresh and pollutant != 'PM25')
            if pollutant != 'PM25': sources.append(record)
            hourly, info = read_hourly(content, pollutant)
            if not (hourly.index.year == year).all():
                raise ValueError('Pollutant file has observations outside its named year')
            info['year'] = year
            quality.append(info)
            years.append(hourly)
        annual.append(pd.concat(years))
    coordinates = {(q['latitude'], q['longitude']) for q in quality}
    latitudes = [pair[0] for pair in coordinates]
    longitudes = [pair[1] for pair in coordinates]
    # Gas exports round coordinates more coarsely than the PM export.
    if max(latitudes)-min(latitudes) > .0001 or max(longitudes)-min(longitudes) > .0001:
        raise ValueError('Pollutants/years do not refer to one stable monitoring location')
    calendar = pd.date_range(f'{start_year}-01-01', f'{end_year}-12-31 23:00:00', freq='h')
    hourly = pd.concat(annual, axis=1).reindex(calendar)
    daily = daily_aqi(hourly, standard)
    weather_columns = [c for c in weather if c not in ('PM25', 'valid_hours')]
    daily = daily.join(weather[weather_columns], validate='one_to_one')
    # A fixed alternative version makes the breakpoint sensitivity explicit,
    # rather than introducing an unexplained definition change in May 2024.
    alternate = 'epa_2024' if standard == 'epa_2018' else 'epa_2018'
    daily[f'AQI_{alternate}'] = daily_aqi(hourly, alternate).AQI
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(output, float_format='%.8f')
    report = {'target': 'AQI', 'units': 'AQI points', 'standard': standard,
              'scope': 'Maximum of the original four pollutants: PM2.5, O3, NO2, SO2; CO and PM10 excluded',
              'status': 'EPA-based reconstruction at Toronto West; not an official published Toronto AQI or Canadian AQHI',
              'standard_reference': 'https://www.airnow.gov/sites/default/files/2020-05/aqi-technical-assistance-document-sept2018.pdf',
              'alternative_reference': 'https://document.airnow.gov/technical-assistance-document-for-the-reporting-of-daily-air-quailty.pdf',
              'minimum_daily_hours': 18, 'ozone_hours_per_8h_window': 6,
              'ozone_daily_windows': '13 of 17 start-hour windows, 07:00–23:00, including next morning',
              'aqi_availability_delay_days': 1, 'calendar_days': len(daily),
              'observed_target_days': int(daily.AQI.notna().sum()),
              'missing_target_days': int(daily.AQI.isna().sum()),
              'component_available_days': {p: int(daily[f'{p}_AQI'].notna().sum()) for p in ('PM25','O3','NO2','SO2')},
              'target_imputation': 'none; any missing component makes the combined AQI unavailable',
              'annual_source_quality': quality, 'naps_station': pm_manifest['naps_station'],
              'weather_station': pm_manifest['weather_station'], 'sources': sources,
              'prepared_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
              'prepared_at': datetime.now(timezone.utc).isoformat()}
    output.with_suffix('.manifest.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    return daily, report
