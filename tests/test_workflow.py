"""Selection isolation, forward dating and snapshot lock regression tests."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from etl_contract import validate
from tests.test_forecast import fixture
from workflow import choose, evaluate, forward, tuning_grid


class WorkflowTests(unittest.TestCase):
    def frame(self):
        frame = fixture().rename(columns={'PM25': 'AQI'})
        return frame

    def test_post_boundary_values_do_not_change_first_prediction_or_training_fit(self):
        frame = self.frame()
        boundary = frame.index[100]
        changed = frame.copy()
        changed.loc[changed.index > boundary, 'AQI'] = 900
        configs = [{'name': 'ridge', 'family': 'ridge', 'alpha': 1.},
                   {'name': 'AR', 'family': 'autoregression'},
                   {'name': 'persistence', 'family': 'persistence'}]
        a, ma = evaluate(frame, boundary, frame.index[-1], configs, horizons=[1,7])
        b, mb = evaluate(changed, boundary, frame.index[-1], configs, horizons=[1,7])
        np.testing.assert_allclose(a.loc[a.origin.eq(boundary), 'predicted'],
                                   b.loc[b.origin.eq(boundary), 'predicted'])
        np.testing.assert_allclose(ma.training_MAE, mb.training_MAE, equal_nan=True)
        self.assertTrue((a.Date > boundary).all())
        self.assertTrue((ma.groupby('horizon').n.nunique() == 1).all())

    def test_evaluation_ignores_everything_after_its_end(self):
        frame = self.frame()
        end = frame.index[-10]
        changed = frame.copy()
        changed.loc[changed.index > end, :] = 999
        config = [{'name': 'ridge', 'family': 'ridge', 'alpha': 1.}]
        a, _ = evaluate(frame, frame.index[100], end, config, horizons=[1])
        b, _ = evaluate(changed, frame.index[100], end, config, horizons=[1])
        pd.testing.assert_frame_equal(a, b)

    def test_selection_and_forward_dates(self):
        configs = [{'name': 'ridge', 'family': 'ridge', 'alpha': 1.},
                   {'name': 'persistence', 'family': 'persistence'}]
        metrics = pd.DataFrame({'model': ['ridge','ridge','persistence','persistence'], 'MAE': [2,4,5,5]})
        selected = choose(metrics, configs)
        self.assertEqual(selected['name'], 'ridge')
        self.assertEqual(len(tuning_grid(selected)), 3)
        forecast = forward(self.frame(), selected)
        self.assertEqual(len(forecast), 7)
        self.assertEqual(forecast.Date.min(), self.frame().index[-1] + pd.Timedelta(days=1))
        self.assertTrue((forecast.Date > forecast.origin).all())

    def test_lock_rejects_changed_record(self):
        source = Path(__file__).resolve().parents[1] / 'data/processed'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ['daily_aqi_latest.csv', 'daily_aqi_latest.manifest.json',
                         'daily_aqi_latest.lock.json', 'hourly_pollution_2020_latest.csv.gz']:
                shutil.copyfile(source / name, root / name)
            path = root / 'daily_aqi_latest.csv'
            validate(path)
            lockpath = path.with_suffix('.lock.json')
            lock = json.loads(lockpath.read_text()); lock['end'] = '2099-01-01'
            lockpath.write_text(json.dumps(lock))
            with self.assertRaises(ValueError):
                validate(path)
