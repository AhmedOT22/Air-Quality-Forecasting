"""Source-format fixtures test quality rules without network access."""
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from data_sources import WEATHER_FIELDS, download, naps_daily, weather_daily, weather_url


def naps_file(rows):
    out = io.StringIO()
    out.write('Units // Unités, µg/m3\nNote,Data is hour ending local standard time\n')
    writer = csv.writer(out)
    names = ['Pollutant', 'Method Code', 'NAPS ID', 'Latitude', 'Longitude', 'Date']
    names += [f'H{h:02d}' for h in range(1, 25)]
    writer.writerow([name + '//' + name for name in names])
    for station, method, date, values in rows:
        writer.writerow(['PM2.5', method, station, '43.70944', '-79.5435', date, *values])
    return out.getvalue().encode()


def weather_payload(hours=24):
    features = []
    for hour in range(hours):
        p = {'CLIMATE_IDENTIFIER': '6158731', 'LOCAL_DATE': f'2024-01-01 {hour:02d}:00:00'}
        for field in WEATHER_FIELDS.values():
            p[field] = 20
            p[field + '_FLAG'] = None
        features.append({'properties': p})
    return {'features': features, 'links': []}


class SourceTests(unittest.TestCase):
    def test_zero_valid_sentinel_and_coverage_threshold(self):
        rows = [('060430', '184', '2024-01-01', [0] * 18 + [-999] * 6),
                ('060430', '184', '2024-01-02', [10] * 17 + [-999] * 7)]
        daily, _ = naps_daily(naps_file(rows), '060430')
        self.assertEqual(daily.PM25.iloc[0], 0)
        self.assertTrue(np.isnan(daily.PM25.iloc[1]))
        self.assertEqual(daily.valid_hours.tolist(), [18, 17])

    def test_methods_combine_complementary_hours_not_daily_means(self):
        rows = [('060430', '184', '2024-01-01', [10] * 6 + [-999] * 18),
                ('060430', '636', '2024-01-01', [-999] * 6 + [20] * 18)]
        daily, report = naps_daily(naps_file(rows), '060430')
        self.assertEqual(daily.PM25.iloc[0], 17.5)
        self.assertEqual(daily.valid_hours.iloc[0], 24)
        self.assertEqual(report['methods'], ['184', '636'])

    def test_conflicting_methods_duplicate_rows_and_wrong_station_rejected(self):
        row = ('060430', '184', '2024-01-01', [1] * 24)
        for rows in ([row, row], [row, ('060430', '636', '2024-01-01', [2] * 24)],
                     [('060410', '184', '2024-01-01', [1] * 24)]):
            with self.subTest(rows=rows[:1]), self.assertRaises(ValueError):
                naps_daily(naps_file(rows), '060430')

    def test_missing_calendar_day_retained(self):
        rows = [('060430', '184', date, [2] * 24) for date in ('2024-01-01', '2024-01-03')]
        daily, _ = naps_daily(naps_file(rows), '060430')
        self.assertEqual(len(daily), 3)
        self.assertTrue(np.isnan(daily.PM25.iloc[1]))
        self.assertEqual(daily.valid_hours.iloc[1], 0)

    def test_weather_flags_coverage_and_calendar_basis(self):
        payload = weather_payload()
        for f in payload['features'][:7]:
            f['properties']['TEMP_FLAG'] = 'M'
        daily = weather_daily(payload, '6158731')
        self.assertTrue(np.isnan(daily.temperature_c.iloc[0]))
        self.assertEqual(daily.temperature_c_hours.iloc[0], 17)
        self.assertEqual(daily.humidity_pct.iloc[0], 20)
        self.assertIn('LOCAL_YEAR=2024', weather_url('6158731', 2024))
        self.assertNotIn('datetime=', weather_url('6158731', 2024))

    def test_weather_duplicate_truncated_or_mixed_station_rejected(self):
        for kind in ('duplicate', 'next', 'station', 'omitted'):
            p = weather_payload()
            if kind == 'duplicate':
                p['features'].append(p['features'][0])
            elif kind == 'next':
                p['links'] = [{'rel': 'next', 'href': 'https://example.com'}]
            elif kind == 'omitted':
                p['numberMatched'] = len(p['features']) + 1
            else:
                p['features'][0]['properties']['CLIMATE_IDENTIFIER'] = 'other'
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                weather_daily(p, '6158731')

    def test_cache_checksum_and_url_enforced(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.csv'
            path.write_bytes(b'observed data')
            with patch('data_sources.urlopen') as network:
                _, record = download('https://example.com/source', path)
                network.assert_not_called()
                self.assertIsNone(record['downloaded_at'])
                path.write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    download('https://example.com/source', path)
