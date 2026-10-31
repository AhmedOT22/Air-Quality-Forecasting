"""Concatenate NAPS history with newer Toronto West hourly observations (2020+)."""
import argparse
import csv
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd

from aqi import DEFAULT_STANDARD, daily_aqi
from aqi_data import read_hourly
from data_sources import DEFAULT_CLIMATE, download, naps_url, weather_daily, weather_url

POLLUTANTS = {'PM25': (124, 'Fine Particulate Matter'), 'O3': (122, 'Ozone'),
              'NO2': (36, 'Nitrogen Dioxide'), 'SO2': (9, 'Sulphur Dioxide')}
HOURS = [f'H{hour:02d}' for hour in range(1, 25)]
EST = timezone(timedelta(hours=-5))


def ontario_url(pollutant, end):
    return 'https://www.airqualityontario.com/history/searchResults.php?' + urlencode({
        'page': 'CSV', 's_categoryId': 'Personal', 's_stationId': '35125',
        's_pollutantId': POLLUTANTS[pollutant][0], 's_startDate': '2020-01-01',
        's_endDate': str(pd.Timestamp(end).date()), 's_reportType': 'CSV'})


def read_ontario(content, pollutant, end):
    """Parse the real CSV, including short current-day rows and trailing commas.

    Duplicate dates with conflicting readings are quarantined, not relabelled or
    averaged. Source rows sometimes repeat a date and omit its following date.
    """
    rows = list(csv.reader(io.StringIO(content.decode('utf-8-sig'))))
    header = next((i for i, row in enumerate(rows) if row[:3] == ['Station ID', 'Pollutant', 'Date']), None)
    if header is None or rows[header][3:27] != HOURS:
        raise ValueError('Unexpected Ontario hourly columns')
    preamble = {row[0]: row[1].strip() for row in rows[:header] if len(row) >= 2}
    unit = 'micrograms per cubic metre' if pollutant == 'PM25' else 'parts per billion'
    if unit not in preamble.get('Unit', ''):
        raise ValueError('Unexpected Ontario concentration unit')
    if abs(float(preamble['Latitude']) - 43.709444) > .0001 or abs(float(preamble['Longitude']) + 79.5435) > .0001:
        raise ValueError('Ontario station location differs from Toronto West')
    if not any(row and row[0] == 'From' and row[-1].endswith(' EST') for row in rows):
        raise ValueError('Ontario CSV must explicitly identify EST time')
    records = []
    for row in rows[header + 1:]:
        if not row or row[0] != '35125':
            if row and row[0].isdigit():
                raise ValueError('Unexpected Ontario station')
            continue
        if row[1] != POLLUTANTS[pollutant][1] or len(row) > 28 or (len(row) == 28 and row[-1].strip()):
            raise ValueError('Unexpected Ontario pollutant or row width')
        records.append(row[:27] + [''] * max(0, 27 - len(row)))
    frame = pd.DataFrame(records, columns=rows[header][:27])
    if frame.empty:
        raise ValueError('No Ontario observations')
    dates = pd.to_datetime(frame.Date, format='%Y-%m-%d', errors='raise')
    if dates.isna().any() or (dates < '2020-01-01').any() or (dates > pd.Timestamp(end)).any():
        raise ValueError('Ontario dates outside requested range')
    duplicated = frame.Date.duplicated(keep=False)
    quarantined = sorted(frame.loc[duplicated, 'Date'].unique().tolist())
    frame = frame.loc[~duplicated].copy()
    long = frame.melt(id_vars='Date', value_vars=HOURS, var_name='hour', value_name='value')
    values = pd.to_numeric(long.value.replace(r'^\s*$', np.nan, regex=True), errors='raise')
    if np.isinf(values).any():
        raise ValueError('Infinite Ontario concentration')
    rejected = int((values.lt(0) | values.eq(9999)).sum())
    values = values.where(values.ge(0) & values.ne(9999))
    # H01 is the first hour-ending interval, represented at its interval start,
    # matching the existing NAPS parser. CSV explicitly uses fixed EST, not EDT.
    timestamps = pd.to_datetime(long.Date) + pd.to_timedelta(long.hour.str[1:].astype(int) - 1, unit='h')
    series = pd.Series(values.to_numpy(), index=pd.DatetimeIndex(timestamps), name=pollutant).sort_index()
    if series.index.has_duplicates:
        raise ValueError('Duplicate Ontario hourly timestamps after quarantine')
    return series, {'pollutant': pollutant, 'received_daily_rows': len(records),
                    'quarantined_duplicate_dates': quarantined,
                    'rejected_missing_or_negative_readings': rejected,
                    'valid_hours': int(series.notna().sum()), 'units': unit,
                    'time_basis': 'Hour-ending intervals in fixed EST (UTC-5), per CSV footer'}


def concatenate_hourly(naps, ontario, boundary, end):
    """Use NAPS through its archive boundary; append Ontario only after it.

    NAPS missing values remain missing: a provisional reading must not silently
    replace a rejected/missing historical measurement. Never average overlaps.
    """
    if naps.index.has_duplicates or ontario.index.has_duplicates:
        raise ValueError('Duplicate hourly source timestamps')
    calendar = pd.date_range('2020-01-01', end, freq='h', name='timestamp_est')
    historical = calendar <= pd.Timestamp(boundary)
    merged = pd.concat([naps.loc[naps.index <= boundary], ontario.loc[ontario.index > boundary]]).reindex(calendar)
    if merged.index.has_duplicates:
        raise ValueError('Concatenation produced duplicate timestamps')
    merged['pollution_source'] = np.where(historical, 'NAPS', 'Ontario')
    merged['verification_status'] = np.where(historical, 'quality_assured_archive', 'not_finally_verified')
    return merged


def extend(end=None, raw_dir='data/raw', output_dir='data/processed', refresh=False):
    now = datetime.now(EST)
    end = pd.Timestamp(end or now.date()).normalize()
    if end < pd.Timestamp('2025-01-01') or end > pd.Timestamp(now.date()):
        raise ValueError('Extension end must be between 2025-01-01 and today')
    raw, output = Path(raw_dir), Path(output_dir)
    frozen = json.loads((output / 'daily_aqi.manifest.json').read_text())
    if frozen['naps_station']['NAPS_ID'] != '060430':
        raise ValueError('Expected Toronto West historical station')
    boundary = pd.Timestamp('2024-12-31 23:00')
    sources = list(frozen['sources'])
    pinned = {record['url']: record['sha256'] for record in sources}
    naps_columns, ontario_columns, quality, overlaps = [], [], [], []
    for pollutant in POLLUTANTS:
        annual = []
        for year in range(2020, 2025):
            path = raw / f'{pollutant}_{year}.csv'
            relative = f'Data-Donnees/{year}/ContinuousData-DonneesContinu/HourlyData-DonneesHoraires/{pollutant}_{year}.csv'
            content, record = download(naps_url(relative), path)
            if record['sha256'] != pinned.get(record['url']):
                raise ValueError('NAPS archive differs from the frozen source record; review before rebuilding')
            annual.append(read_hourly(content, pollutant)[0])
        history = pd.concat(annual)
        url = ontario_url(pollutant, end)
        # Names include the requested endpoint so frozen exports are reproducible.
        path = raw / 'ontario' / f'{pollutant}_2020_{end.date()}.csv'
        content, record = download(url, path, refresh)
        recent, info = read_ontario(content, pollutant, end)
        sources.append(record)
        quality.append(info)
        paired = pd.concat([history.rename('NAPS'), recent.rename('Ontario')], axis=1).loc[:boundary].dropna()
        overlaps.append({'pollutant': pollutant, 'comparable_hours': len(paired),
                         'mean_absolute_difference': float((paired.NAPS - paired.Ontario).abs().mean()),
                         'exactly_equal_hours': int(paired.NAPS.eq(paired.Ontario).sum())})
        naps_columns.append(history)
        ontario_columns.append(recent)
    latest = max(series.last_valid_index() for series in ontario_columns)
    hourly = concatenate_hourly(pd.concat(naps_columns, axis=1), pd.concat(ontario_columns, axis=1),
                                boundary, min(latest, end + pd.Timedelta(hours=23)))
    # Retain available current-day hours above, but exclude incomplete current days
    # from the daily modelling input. Next-morning hours still inform ozone windows.
    daily = daily_aqi(hourly[list(POLLUTANTS)], DEFAULT_STANDARD)
    daily['AQI_epa_2018'] = daily_aqi(hourly[list(POLLUTANTS)], 'epa_2018').AQI
    completed_end = min(end, pd.Timestamp(now.date()) - pd.Timedelta(days=1), latest.normalize())
    daily = daily.loc[:completed_end].copy()
    weather_frames = []
    for year in range(2020, completed_end.year + 1):
        content, record = download(weather_url(DEFAULT_CLIMATE, year), raw / f'weather_{year}.json',
                                   refresh=refresh and year >= 2025)
        weather = weather_daily(json.loads(content), DEFAULT_CLIMATE)
        if not (weather.index.year == year).all():
            raise ValueError('Weather observations outside requested year')
        weather_frames.append(weather)
        if year >= 2025:
            sources.append(record)
    daily = daily.join(pd.concat(weather_frames), validate='one_to_one')
    daily['naps_station_id'] = '060430'
    daily['ontario_station_id'] = '35125'
    daily['pollution_source'] = np.where(daily.index <= boundary, 'NAPS', 'Ontario')
    daily['aqi_input_source'] = daily.pollution_source
    if pd.Timestamp('2024-12-31') in daily.index:
        daily.loc['2024-12-31', 'aqi_input_source'] = 'NAPS|Ontario'
    daily['verification_status'] = np.where(daily.aqi_input_source.eq('NAPS'),
                                            'quality_assured_archive', 'includes_unverified_observations')
    output.mkdir(parents=True, exist_ok=True)
    hourly_path = output / 'hourly_pollution_2020_latest.csv.gz'
    hourly.to_csv(hourly_path, float_format='%.8f', compression={'method': 'gzip', 'mtime': 0})
    daily_path = output / 'daily_aqi_latest.csv'
    daily.to_csv(daily_path, float_format='%.8f')
    manifest = {**{k: frozen[k] for k in ('target', 'units', 'scope', 'status', 'standard', 'standard_reference',
        'alternative_reference', 'minimum_daily_hours', 'ozone_hours_per_8h_window', 'ozone_daily_windows',
        'aqi_availability_delay_days', 'target_imputation', 'naps_station', 'weather_station')},
        'start': '2020-01-01', 'end': str(daily.index[-1].date()),
        'requested_ontario_end': str(end.date()), 'latest_pollution_hour_est': str(latest),
        'time_basis': 'Fixed local standard time UTC-5, hour-ending intervals stored at interval starts',
        'source_priority': 'NAPS 2020-2024 including its gaps; Ontario from 2025 onward; no overlap averaging',
        'ontario_station_id': '35125', 'verification_policy': 'Ontario final verification not established; flagged explicitly',
        'duplicate_policy': 'Quarantine all rows on repeated Ontario dates; no inferred date repairs',
        'quality': quality, 'overlap_comparison': overlaps,
        'calendar_days': len(daily), 'observed_target_days': int(daily.AQI.notna().sum()),
        'missing_target_days': int(daily.AQI.isna().sum()),
        'coverage_by_year': {str(year): {'days': len(group), 'complete_aqi_days': int(group.AQI.notna().sum())}
                             for year, group in daily.groupby(daily.index.year)},
        'hourly_file': hourly_path.name, 'hourly_sha256': hashlib.sha256(hourly_path.read_bytes()).hexdigest(),
        'prepared_sha256': hashlib.sha256(daily_path.read_bytes()).hexdigest(),
        'sources': sources, 'prepared_at': datetime.now(timezone.utc).isoformat()}
    daily_path.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    return daily, manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--end-date', help='Last requested observation day; defaults to today in EST')
    parser.add_argument('--raw-dir', type=Path, default=Path('data/raw'))
    parser.add_argument('--output-dir', type=Path, default=Path('data/processed'))
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    _, report = extend(args.end_date, args.raw_dir, args.output_dir, args.refresh)
    print(json.dumps({k: report[k] for k in ('start', 'end', 'latest_pollution_hour_est',
                                           'calendar_days', 'observed_target_days', 'missing_target_days')}, indent=2))
