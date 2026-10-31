"""Download, validate and prepare station-specific NAPS/ECCC observations."""

import argparse
import csv
import hashlib
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

CATALOGUE = 'https://data-donnees.az.ec.gc.ca/api/'
NAPS_ROOT = '/air/monitor/national-air-pollution-surveillance-naps-program/'
WEATHER_API = 'https://api.weather.gc.ca/collections/'
WEATHER_FIELDS = {
    'temperature_c': 'TEMP',
    'humidity_pct': 'RELATIVE_HUMIDITY',
    'wind_speed_kmh': 'WIND_SPEED',
    'pressure_kpa': 'STATION_PRESSURE',
}
DEFAULT_STATION = '060430'
DEFAULT_CLIMATE = '6158731'


def naps_url(path):
    return CATALOGUE + 'file?' + urlencode({'path': NAPS_ROOT + path})


def weather_url(climate_id, year):
    # Filter LOCAL_YEAR explicitly: this collection indexes local observation
    # dates for temporal queries. Do not apply a UTC offset to datetime bounds.
    properties = ['CLIMATE_IDENTIFIER', 'LOCAL_DATE']
    for field in WEATHER_FIELDS.values():
        properties.extend([field, field + '_FLAG'])
    return WEATHER_API + 'climate-hourly/items?' + urlencode({
        'f': 'json', 'CLIMATE_IDENTIFIER': climate_id,
        'LOCAL_YEAR': year,
        'limit': 10000, 'properties': ','.join(properties),
    })


def download(url, destination, refresh=False):
    """Cache source bytes with a checksum; never silently accept changed cache files."""
    destination = Path(destination)
    sidecar = destination.with_suffix(destination.suffix + '.source.json')
    if destination.exists() and not refresh:
        content = destination.read_bytes()
        info = json.loads(sidecar.read_text()) if sidecar.exists() else {}
        digest = hashlib.sha256(content).hexdigest()
        if info and (info['sha256'] != digest or info['url'] != url):
            raise ValueError(f'Cache differs from its source record: {destination}; use --refresh')
        if not info:
            info = {'url': url, 'sha256': digest, 'downloaded_at': None,
                    'note': 'Pre-existing local cache; original retrieval timestamp unavailable.'}
            sidecar.write_text(json.dumps(info, indent=2) + '\n')
        return content, info
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            request = Request(url, headers={'User-Agent': 'Toronto-PM25-research/1.0'})
            with urlopen(request, timeout=120) as response:
                content = response.read()
                headers = dict(response.headers)
            if content.lstrip().lower().startswith((b'<!doctype html', b'<html')):
                raise ValueError(f'Expected source data, received HTML from {url}')
            break
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    info = {'url': url, 'sha256': hashlib.sha256(content).hexdigest(),
            'downloaded_at': datetime.now(timezone.utc).isoformat(),
            'last_modified': headers.get('Last-Modified'), 'bytes': len(content)}
    temporary = destination.with_suffix(destination.suffix + '.tmp')
    temporary.write_bytes(content)
    temporary.replace(destination)
    sidecar.write_text(json.dumps(info, indent=2) + '\n')
    return content, info


def naps_daily(content, station_id, min_hours=18):
    """Keep station/method/hour identity; combine only non-overlapping method records."""
    if not 1 <= min_hours <= 24:
        raise ValueError('min_hours must be between 1 and 24')
    text = content.decode('utf-8-sig')
    if 'µg/m3' not in text[:1000] or 'hour ending local standard time' not in text[:1000]:
        raise ValueError('Unexpected NAPS PM2.5 units or time convention')
    lines = text.splitlines()
    header = next((i for i, line in enumerate(lines) if 'NAPS ID//' in line), None)
    if header is None:
        raise ValueError('NAPS column header not found')
    frame = pd.read_csv(io.StringIO('\n'.join(lines[header:])), dtype=str)
    frame.columns = [name.split('//')[0].strip() for name in frame.columns]
    required = {'NAPS ID', 'Method Code', 'Date', 'Pollutant', 'Latitude', 'Longitude'}
    hours = [f'H{hour:02d}' for hour in range(1, 25)]
    if not (required | set(hours)).issubset(frame.columns):
        raise ValueError('Missing required NAPS columns')
    frame = frame.loc[frame['NAPS ID'].eq(str(station_id).zfill(6))].copy()
    if frame.empty or not frame['Pollutant'].eq('PM2.5').all():
        raise ValueError(f'No PM2.5 records for station {station_id}')
    if frame.duplicated(['NAPS ID', 'Method Code', 'Date']).any():
        raise ValueError('Duplicate station/method/day records')
    if len(frame[['Latitude', 'Longitude']].drop_duplicates()) != 1:
        raise ValueError('Station coordinates change within source file; review station history')
    frame['Date'] = pd.to_datetime(frame['Date'], format='%Y-%m-%d', errors='raise')
    if frame.Date.isna().any():
        raise ValueError('Missing NAPS date')
    long = frame.melt(id_vars=['Date', 'Method Code'], value_vars=hours,
                      var_name='hour', value_name='value')
    long['value'] = pd.to_numeric(long['value'], errors='raise')
    if np.isinf(long['value']).any():
        raise ValueError('Infinite PM2.5 observation')
    # -999 is the published missing sentinel. Other negative measurements cannot
    # form a non-negative concentration target and are counted separately.
    negative = long['value'].lt(0) & long['value'].ne(-999)
    valid = long.loc[long['value'].ge(0)].copy()  # zero remains a valid measurement
    if valid.duplicated(['Date', 'hour']).any():
        raise ValueError('Overlapping valid instrument-method readings; manual review required')
    grouped = valid.groupby('Date')['value'].agg(['mean', 'count'])
    daily = grouped.rename(columns={'mean': 'PM25', 'count': 'valid_hours'})
    daily = daily.reindex(pd.date_range(frame.Date.min(), frame.Date.max(), freq='D'))
    daily['valid_hours'] = daily['valid_hours'].fillna(0).astype(int)
    daily.loc[daily.valid_hours < min_hours, 'PM25'] = np.nan
    daily['naps_station_id'] = str(station_id).zfill(6)
    daily.index.name = 'Date'
    info = {'methods': sorted(frame['Method Code'].unique().tolist()),
            'latitude': float(frame.Latitude.iloc[0]), 'longitude': float(frame.Longitude.iloc[0]),
            'rejected_negative_hours_excluding_sentinel': int(negative.sum()),
            'valid_days': int(daily.PM25.notna().sum()), 'days': len(daily)}
    return daily, info


def station_metadata(content, station_id):
    rows = list(csv.reader(io.StringIO(content.decode('utf-8-sig'))))
    header = next((i for i, row in enumerate(rows) if row and row[0] == 'NAPS_ID'), None)
    if header is None:
        raise ValueError('NAPS station metadata header not found')
    matches = [dict(zip(rows[header], row)) for row in rows[header + 1:]
               if row and row[0] == str(station_id).zfill(6)]
    if len(matches) != 1:
        raise ValueError('Station metadata must match exactly one record')
    return matches[0]


def weather_daily(payload, climate_id, min_hours=18):
    if not 1 <= min_hours <= 24:
        raise ValueError('min_hours must be between 1 and 24')
    if any(link.get('rel') == 'next' for link in payload.get('links', [])):
        raise ValueError('Weather response is paginated; refusing truncated annual data')
    features = payload.get('features', [])
    matched = payload.get('numberMatched')
    if isinstance(matched, int) and matched > len(features):
        raise ValueError('Weather response has omitted matching observations')
    rows = [feature['properties'] for feature in features]
    frame = pd.DataFrame(rows)
    if frame.empty or not frame['CLIMATE_IDENTIFIER'].astype(str).eq(climate_id).all():
        raise ValueError('Missing or mixed climate station records')
    dates = pd.to_datetime(frame['LOCAL_DATE'], errors='raise')
    if dates.isna().any() or dates.dt.tz is not None or dates.duplicated().any() or not dates.eq(dates.dt.floor('h')).all():
        raise ValueError('Duplicate or non-hourly weather timestamps')
    day = dates.dt.normalize()
    daily = pd.DataFrame(index=pd.DatetimeIndex(day.unique()).sort_values())
    for name, field in WEATHER_FIELDS.items():
        values = pd.to_numeric(frame[field], errors='raise')
        # Retain all original flags in cached raw JSON. Conservative preparation
        # uses only unflagged, finite observations.
        values = values.where(frame[field + '_FLAG'].isna() & np.isfinite(values))
        if name == 'humidity_pct':
            values = values.where(values.between(0, 100))
        if name == 'wind_speed_kmh':
            values = values.where(values >= 0)
        if name == 'pressure_kpa':
            values = values.where(values > 0)
        stats = values.groupby(day).agg(['mean', 'count'])
        daily[name] = stats['mean'].where(stats['count'] >= min_hours)
        daily[name + '_hours'] = stats['count']
    daily['climate_station_id'] = climate_id
    daily.index.name = 'Date'
    return daily


def prepare(start_year=2020, end_year=2024, raw_dir='data/raw', output='data/processed/daily_pm25.csv',
            station_id=DEFAULT_STATION, climate_id=DEFAULT_CLIMATE, min_hours=18, refresh=False):
    if start_year > end_year:
        raise ValueError('start_year must not exceed end_year')
    # The supported pairing is explicit; other timezones need different UTC
    # query boundaries, not merely a station-number substitution.
    if station_id != DEFAULT_STATION or climate_id != DEFAULT_CLIMATE:
        raise ValueError('This configuration supports Toronto West / Toronto Intl A only')
    raw = Path(raw_dir)
    sources, pollution, weather, quality = [], [], [], []
    content, record = download(naps_url('ProgramInformation-InformationProgramme/StationsNAPS-StationsSNPA.csv'),
                               raw / 'naps_stations.csv', refresh)
    sources.append(record)
    station = station_metadata(content, station_id)
    if station['Timezone_UTC'] != '-5':
        raise ValueError('Expected an EST monitoring station')
    if pd.Timestamp(station['Start_Date']) > pd.Timestamp(start_year, 1, 1) or (
            station['End_Date'] and pd.Timestamp(station['End_Date']) < pd.Timestamp(end_year, 12, 31)):
        raise ValueError('Station metadata does not cover the requested period')
    station_url = WEATHER_API + 'climate-stations/items?' + urlencode({
        'f': 'json', 'CLIMATE_IDENTIFIER': climate_id, 'limit': 10})
    content, record = download(station_url, raw / 'weather_station.json', refresh)
    sources.append(record)
    stations = json.loads(content).get('features', [])
    if len(stations) != 1 or stations[0]['properties']['TIMEZONE'] != 'EST':
        raise ValueError('Expected exactly one EST climate station')
    weather_station = stations[0]
    properties = weather_station['properties']
    if properties['CLIMATE_IDENTIFIER'] != climate_id or (
            pd.Timestamp(properties['HLY_FIRST_DATE']) > pd.Timestamp(start_year, 1, 1) or
            pd.Timestamp(properties['HLY_LAST_DATE']) < pd.Timestamp(end_year, 12, 31, 23)):
        raise ValueError('Climate station metadata does not cover the requested period')
    for year in range(start_year, end_year + 1):
        path = f'Data-Donnees/{year}/ContinuousData-DonneesContinu/HourlyData-DonneesHoraires/PM25_{year}.csv'
        content, record = download(naps_url(path), raw / f'PM25_{year}.csv', refresh)
        sources.append(record)
        daily, report = naps_daily(content, station_id, min_hours)
        if not (daily.index.year == year).all():
            raise ValueError('NAPS file contains dates outside its requested year')
        report['year'] = year
        quality.append(report)
        pollution.append(daily)
        content, record = download(weather_url(climate_id, year), raw / f'weather_{year}.json', refresh)
        sources.append(record)
        daily_weather = weather_daily(json.loads(content), climate_id, min_hours)
        if not (daily_weather.index.year == year).all():
            raise ValueError('Weather file contains dates outside its requested year')
        weather.append(daily_weather)
    coords = {(q['latitude'], q['longitude']) for q in quality}
    if len(coords) != 1:
        raise ValueError('Pollution station location changes across years')
    pollution = pd.concat(pollution)
    weather = pd.concat(weather)
    if pollution.index.has_duplicates or weather.index.has_duplicates:
        raise ValueError('Overlapping annual source dates')
    calendar = pd.date_range(f'{start_year}-01-01', f'{end_year}-12-31', freq='D', name='Date')
    daily = pollution.join(weather, how='outer', validate='one_to_one').reindex(calendar)
    daily['naps_station_id'] = station_id
    daily['climate_station_id'] = climate_id
    daily['valid_hours'] = daily['valid_hours'].fillna(0).astype(int)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(output, float_format='%.8f')
    report = {'target': 'Daily mean PM2.5 concentration', 'units': 'µg/m³',
              'start': str(calendar[0].date()), 'end': str(calendar[-1].date()),
              'time_basis': 'Local standard time UTC-5; no daylight saving shifts',
              'minimum_hours_per_day': min_hours, 'calendar_days': len(daily),
              'observed_target_days': int(daily.PM25.notna().sum()),
              'missing_target_days': int(daily.PM25.isna().sum()),
              'target_imputation': 'none', 'naps_station': station,
              'weather_station': weather_station, 'annual_quality': quality,
              'weather_observed_days': {name: int(daily[name].notna().sum()) for name in WEATHER_FIELDS},
              'prepared_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
              'sources': sources, 'prepared_at': datetime.now(timezone.utc).isoformat()}
    output.with_suffix('.manifest.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    return daily, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-year', type=int, default=2020)
    parser.add_argument('--end-year', type=int, default=2024)
    parser.add_argument('--raw-dir', type=Path, default=Path('data/raw'))
    parser.add_argument('--output', type=Path, default=Path('data/processed/daily_pm25.csv'))
    parser.add_argument('--min-hours', type=int, default=18)
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    try:
        _, report = prepare(args.start_year, args.end_year, args.raw_dir, args.output,
                            min_hours=args.min_hours, refresh=args.refresh)
        print(json.dumps({k: report[k] for k in ('calendar_days', 'observed_target_days', 'missing_target_days')}, indent=2))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f'Data preparation failed: {error}\n')


if __name__ == '__main__':
    main()
