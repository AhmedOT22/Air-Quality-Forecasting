"""Offline integration checks against the committed official-data snapshot."""
import hashlib
import json
import unittest
from pathlib import Path

from forecast import load_data

ROOT = Path(__file__).resolve().parents[1]


class SnapshotTests(unittest.TestCase):
    def test_snapshot_matches_manifest_and_quality_counts(self):
        path = ROOT / 'data/processed/daily_pm25.csv'
        metadata = json.loads(path.with_suffix('.manifest.json').read_text())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), metadata['prepared_sha256'])
        data = load_data(path)
        self.assertEqual(len(data), metadata['calendar_days'])
        self.assertEqual(int(data.PM25.notna().sum()), metadata['observed_target_days'])
        self.assertEqual(data.index[0].strftime('%Y-%m-%d'), metadata['start'])
        self.assertEqual(data.index[-1].strftime('%Y-%m-%d'), metadata['end'])
        self.assertTrue((data.loc[data.PM25.notna(), 'valid_hours'] >= metadata['minimum_hours_per_day']).all())
        self.assertTrue((data.valid_hours <= 24).all())
        for source in metadata['sources']:
            self.assertEqual(len(source['sha256']), 64)
            self.assertTrue(source['url'].startswith('https://'))

    def test_aqi_snapshot_preserves_four_component_definition(self):
        import pandas as pd
        path = ROOT / 'data/processed/daily_aqi.csv'
        metadata = json.loads(path.with_suffix('.manifest.json').read_text())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), metadata['prepared_sha256'])
        data = load_data(path)
        columns = ['PM25_AQI','O3_AQI','NO2_AQI','SO2_AQI']
        complete = data[columns].notna().all(axis=1)
        self.assertTrue(data.loc[~complete, 'AQI'].isna().all())
        pd.testing.assert_series_equal(data.loc[complete, 'AQI'],
                                       data.loc[complete, columns].max(axis=1), check_names=False)
        self.assertEqual(int(data.AQI.notna().sum()), metadata['observed_target_days'])
        self.assertEqual(metadata['aqi_availability_delay_days'], 1)
        from aqi import DEFAULT_STANDARD, category, pm25_index
        self.assertEqual(metadata['standard'], DEFAULT_STANDARD)
        self.assertTrue(data.aqi_standard.eq(DEFAULT_STANDARD).all())
        pd.testing.assert_series_equal(data.PM25_AQI, data.PM25_mean_24h.map(pm25_index), check_names=False)
        legacy_components = data[columns].copy()
        legacy_components['PM25_AQI'] = data.PM25_mean_24h.map(lambda value: pm25_index(value, 'epa_2018'))
        legacy = legacy_components.max(axis=1).where(complete)
        pd.testing.assert_series_equal(data.AQI_epa_2018, legacy, check_names=False)
        pd.testing.assert_series_equal(data.AQI_category, data.AQI.map(category), check_names=False)
        comparison = metadata['breakpoint_comparison']
        self.assertEqual(comparison['changed_aqi_days'], int(data.loc[complete, 'AQI'].ne(legacy[complete]).sum()))
        self.assertEqual(comparison['changed_category_days'], int(data.loc[complete, 'AQI_category'].ne(legacy[complete].map(category)).sum()))
