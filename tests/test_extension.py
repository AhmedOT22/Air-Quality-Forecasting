"""Regression checks for the downloaded Ontario CSV and cross-source concatenation."""
import hashlib
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from extend_data import concatenate_hourly, read_ontario
from forecast import load_data


def ontario_fixture(rows):
    header = ','.join(['Station ID', 'Pollutant', 'Date'] + [f'H{i:02d}' for i in range(1, 25)])
    preamble = ('Station,Toronto West (35125)\nLatitude,43.709444\nLongitude,-79.5435\n'
                'Unit, parts per billion (ppb)\nRemarks, 9999 for invalid or missing data.\n')
    return (preamble + header + '\n' + '\n'.join(rows) + '\nFrom,January 1, 2020 EST\n').encode()


def row(day, values):
    return ','.join(['35125', 'Ozone', day] + [str(v) for v in values]) + ','


class ExtensionTests(unittest.TestCase):
    def test_short_rows_sentinels_and_zero_preserved(self):
        content = ontario_fixture([row('2026-10-30', [0, 9999, -999] + [10] * 21),
                                   row('2026-10-31', [4, 5])])
        values, info = read_ontario(content, 'O3', '2026-10-31')
        self.assertEqual(values.loc['2026-10-30 00:00'], 0)
        self.assertTrue(np.isnan(values.loc['2026-10-30 01:00']))
        self.assertTrue(np.isnan(values.loc['2026-10-30 02:00']))
        self.assertEqual(values.loc['2026-10-31 01:00'], 5)
        self.assertTrue(np.isnan(values.loc['2026-10-31 02:00']))
        self.assertEqual(info['rejected_missing_or_negative_readings'], 2)

    def test_conflicting_duplicate_dates_are_quarantined_not_averaged(self):
        content = ontario_fixture([row('2026-05-08', [1] * 24), row('2026-05-08', [2] * 24),
                                   row('2026-05-10', [3] * 24)])
        values, info = read_ontario(content, 'O3', '2026-05-10')
        self.assertNotIn(pd.Timestamp('2026-05-08'), values.index)
        self.assertEqual(info['quarantined_duplicate_dates'], ['2026-05-08'])
        self.assertEqual(len(values), 24)

    def test_wrong_units_station_time_basis_and_pre2020_rows_rejected(self):
        content = ontario_fixture([row('2026-01-01', [1] * 24)])
        for bad in (content.replace(b'parts per billion', b'parts per million'),
                    content.replace(b'35125,Ozone', b'35126,Ozone'),
                    content.replace(b' EST', b' EDT'),
                    content.replace(b'2026-01-01', b'2019-12-31')):
            with self.subTest(content=bad[:80]), self.assertRaises(ValueError):
                read_ontario(bad, 'O3', '2026-10-31')

    def test_archive_priority_retains_historical_gaps_and_appends_only_new_hours(self):
        ix = pd.date_range('2024-12-31 22:00', periods=4, freq='h')
        historical = pd.DataFrame({'O3': [1., np.nan]}, index=ix[:2])
        recent = pd.DataFrame({'O3': [99., 88., 3., 4.]}, index=ix)
        result = concatenate_hourly(historical, recent, pd.Timestamp('2024-12-31 23:00'), ix[-1])
        self.assertEqual(result.O3.loc[ix[0]], 1)
        self.assertTrue(np.isnan(result.O3.loc[ix[1]]))
        self.assertEqual(result.O3.loc[ix[2]], 3)
        self.assertEqual(result.pollution_source.loc[ix[1]], 'NAPS')
        self.assertEqual(result.pollution_source.loc[ix[2]], 'Ontario')
        self.assertFalse(result.index.has_duplicates)
        self.assertEqual(result.index[0], pd.Timestamp('2020-01-01'))

    def test_committed_extension_matches_provenance_and_preserves_archive(self):
        root = Path(__file__).resolve().parents[1]
        path = root / 'data/processed/daily_aqi_latest.csv'
        manifest = json.loads(path.with_suffix('.manifest.json').read_text())
        daily = load_data(path)
        hourly_path = path.parent / manifest['hourly_file']
        self.assertEqual(hashlib.sha256(hourly_path.read_bytes()).hexdigest(), manifest['hourly_sha256'])
        hourly = pd.read_csv(hourly_path, parse_dates=['timestamp_est']).set_index('timestamp_est')
        self.assertEqual(hourly.index[0], pd.Timestamp('2020-01-01'))
        self.assertFalse(hourly.index.has_duplicates)
        self.assertTrue(hourly.index.equals(pd.date_range(hourly.index[0], hourly.index[-1], freq='h')))
        self.assertEqual(int(daily.AQI.notna().sum()), manifest['observed_target_days'])
        self.assertGreater(daily.index[-1], pd.Timestamp('2024-12-31'))
        original = load_data(root / 'data/processed/daily_aqi.csv')
        # Dec 31 now has the next morning's Ontario ozone, explicitly marked mixed.
        pd.testing.assert_series_equal(daily.AQI.loc[:'2024-12-30'], original.AQI.loc[:'2024-12-30'])
        self.assertEqual(daily.loc['2024-12-31', 'aqi_input_source'], 'NAPS|Ontario')
        for info in manifest['quality']:
            for date in info['quarantined_duplicate_dates']:
                if date >= '2025-01-01':
                    self.assertTrue(hourly.loc[date, info['pollutant']].isna().all())
