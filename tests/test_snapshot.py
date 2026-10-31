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
