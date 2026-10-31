"""Versioned EPA-based AQI sub-indices for the original four-pollutant task.

Reconstruction at one Canadian monitor, not an official published Toronto AQI.
References: EPA 454/B-18-007 (2018) and EPA-454/B-24-002 (May 2024).
"""
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

import numpy as np
import pandas as pd

STANDARDS = ('epa_2018', 'epa_2024')
INDEX_BANDS = [(0, 50), (51, 100), (101, 150), (151, 200), (201, 300), (301, 400), (401, 500)]
PM25_2018 = [(0, 12), (12.1, 35.4), (35.5, 55.4), (55.5, 150.4),
             (150.5, 250.4), (250.5, 350.4), (350.5, 500.4)]
PM25_2024 = [(0, 9), (9.1, 35.4), (35.5, 55.4), (55.5, 125.4),
             (125.5, 225.4), (225.5, 325.4)]
NO2 = [(0, 53), (54, 100), (101, 360), (361, 649), (650, 1249), (1250, 1649), (1650, 2049)]
SO2_LOW = [(0, 35), (36, 75), (76, 185), (186, 304)]
SO2_HIGH = [(305, 604), (605, 804), (805, 1004)]
O3_8H = [(0, .054), (.055, .070), (.071, .085), (.086, .105), (.106, .200)]
O3_1H = [(.125, .164), (.165, .204), (.205, .404), (.405, .504), (.505, .604)]


def concentration_index(value, breakpoints, bands, decimals, extrapolate=False):
    """Truncate concentration first; interpolate; round half-up (not Python banker's rounding)."""
    if pd.isna(value):
        return np.nan
    if not np.isfinite(value) or value < 0:
        raise ValueError('Concentration must be finite and non-negative')
    quantum = Decimal(1).scaleb(-decimals)
    concentration = Decimal(str(value)).quantize(quantum, rounding=ROUND_DOWN)
    selected = None
    for (low, high), (i_low, i_high) in zip(breakpoints, bands):
        if Decimal(str(low)) <= concentration <= Decimal(str(high)):
            selected = low, high, i_low, i_high
            break
    if selected is None and extrapolate and concentration > Decimal(str(breakpoints[-1][1])):
        selected = *breakpoints[-1], *bands[-1]
    if selected is None:
        return np.nan  # undefined range, e.g. low 1-hour ozone
    low, high, i_low, i_high = map(lambda x: Decimal(str(x)), selected)
    index = (i_high - i_low) / (high - low) * (concentration - low) + i_low
    return int(index.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def pm25_index(mean_24h, standard='epa_2018'):
    if standard not in STANDARDS:
        raise ValueError('Unknown AQI breakpoint version')
    if standard == 'epa_2024':
        bands = INDEX_BANDS[:5] + [(301, 500)]
        return concentration_index(mean_24h, PM25_2024, bands, 1, extrapolate=True)
    return concentration_index(mean_24h, PM25_2018, INDEX_BANDS, 1, extrapolate=True)


def no2_index(max_1h):
    return concentration_index(max_1h, NO2, INDEX_BANDS, 0, extrapolate=True)


def so2_index(max_1h, mean_24h):
    if pd.isna(max_1h) or pd.isna(mean_24h):
        return np.nan
    if mean_24h >= 305:
        return concentration_index(mean_24h, SO2_HIGH, INDEX_BANDS[4:], 0, extrapolate=True)
    if max_1h >= 305:
        return 200
    return concentration_index(max_1h, SO2_LOW, INDEX_BANDS[:4], 0)


def ozone_index(max_8h_ppb, max_1h_ppb):
    if pd.isna(max_8h_ppb) or pd.isna(max_1h_ppb):
        return np.nan
    eight = concentration_index(max_8h_ppb / 1000, O3_8H, INDEX_BANDS[:5], 3)
    one = concentration_index(max_1h_ppb / 1000, O3_1H, INDEX_BANDS[2:], 3, extrapolate=True)
    defined = [value for value in (eight, one) if not pd.isna(value)]
    return max(defined) if defined else np.nan


def category(value):
    if pd.isna(value):
        return 'Missing'
    for upper, label in [(50, 'Good'), (100, 'Moderate'), (150, 'Unhealthy for Sensitive Groups'),
                         (200, 'Unhealthy'), (300, 'Very Unhealthy')]:
        if value <= upper:
            return label
    return 'Hazardous'


def daily_aqi(hourly, standard='epa_2018'):
    """Four-pollutant AQI; strict component completeness, no partial maxima.

    Hourly indices are interval-start timestamps in fixed local standard time.
    Ozone uses 17 windows starting 07–23 (crossing into the next morning).
    Each window needs 6/8 hours and each day needs 13/17 valid windows.
    The resulting AQI is conservatively available after the following day.
    """
    required = {'PM25', 'O3', 'NO2', 'SO2'}
    if not required <= set(hourly):
        raise ValueError('Need all four original AQI pollutants')
    if not isinstance(hourly.index, pd.DatetimeIndex) or hourly.index.has_duplicates:
        raise ValueError('Expected unique hourly timestamps')
    if not hourly.index.equals(pd.date_range(hourly.index[0], hourly.index[-1], freq='h')):
        raise ValueError('Retain all hourly slots before aggregating AQI')
    if ((hourly[list(required)] < 0) | np.isinf(hourly[list(required)])).any().any():
        raise ValueError('Missing observations must be NaN; concentrations cannot be negative/infinite')
    dates = hourly.index.normalize()
    daily = pd.DataFrame(index=pd.date_range(dates.min(), dates.max(), freq='D', name='Date'))
    for pollutant in sorted(required):
        stats = hourly[pollutant].groupby(dates).agg(['mean', 'max', 'count'])
        qualified = stats['count'] >= 18
        daily[f'{pollutant}_valid_hours'] = stats['count']
        daily[f'{pollutant}_mean_24h'] = stats['mean'].where(qualified)
        daily[f'{pollutant}_max_1h'] = stats['max'].where(qualified)
    averages = hourly.O3.rolling(8, min_periods=6).mean().shift(-7)
    windows = averages.loc[(hourly.index.hour >= 7) & (hourly.index.hour <= 23)]
    ozone = windows.groupby(windows.index.normalize()).agg(['max', 'count'])
    daily['O3_valid_8h_windows'] = ozone['count']
    daily['O3_max_8h_ppb'] = ozone['max'].where(ozone['count'] >= 13)
    daily['PM25_AQI'] = daily.PM25_mean_24h.map(lambda x: pm25_index(x, standard))
    daily['NO2_AQI'] = daily.NO2_max_1h.map(no2_index)
    daily['SO2_AQI'] = [so2_index(a, b) for a, b in zip(daily.SO2_max_1h, daily.SO2_mean_24h)]
    daily['O3_AQI'] = [ozone_index(a, b) for a, b in zip(daily.O3_max_8h_ppb, daily.O3_max_1h)]
    columns = [f'{p}_AQI' for p in ('PM25', 'O3', 'NO2', 'SO2')]
    complete = daily[columns].notna().all(axis=1)
    daily['AQI'] = daily[columns].max(axis=1).where(complete)
    daily['AQI_components_available'] = daily[columns].notna().sum(axis=1)
    daily['dominant_pollutant'] = [
        '|'.join(column.removesuffix('_AQI') for column in columns if row[column] == row.AQI)
        if not pd.isna(row.AQI) else '' for _, row in daily.iterrows()]
    daily['AQI_category'] = daily.AQI.map(category)
    daily['aqi_standard'] = standard
    daily['aqi_available_after'] = daily.index + pd.Timedelta(days=1)
    return daily
