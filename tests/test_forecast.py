"""Deterministic tests for forecasting availability, gaps and fair evaluation."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from data_sources import WEATHER_FIELDS
from forecast import backtest, fit_horizon, future_forecast, load_data, make_features, run


def fixture():
    n = 160
    frame = pd.DataFrame({'PM25': 12 + np.sin(np.arange(n) / 4) * 5},
                         index=pd.date_range('2023-10-01', periods=n, name='Date'))
    for i, name in enumerate(WEATHER_FIELDS):
        frame[name] = np.arange(n) / 10 + i
    frame['naps_station_id'] = '060430'
    frame['climate_station_id'] = '6158731'
    return frame


class ForecastTests(unittest.TestCase):
    def test_features_reference_completed_origin_and_known_target_calendar(self):
        frame = fixture()
        f, _, _ = make_features(frame, 7)
        origin = frame.index[20]
        self.assertEqual(f.loc[origin, 'pm25_lag_0'], frame.PM25.iloc[20])
        self.assertEqual(f.loc[origin, 'pm25_lag_13'], frame.PM25.iloc[7])
        self.assertEqual(f.loc[origin, 'temperature_c'], frame.temperature_c.iloc[20])
        self.assertAlmostEqual(f.loc[origin, 'pm25_mean_7d'], frame.PM25.iloc[14:21].mean())

    def test_future_pollution_and_weather_do_not_change_first_trajectory(self):
        frame = fixture()
        changed = frame.copy()
        changed.iloc[-20:, changed.columns.get_indexer(['PM25', *WEATHER_FIELDS])] = 999
        a, _ = backtest(frame, test_days=20, horizon=7, trees=3)
        b, _ = backtest(changed, test_days=20, horizon=7, trees=3)
        cols = ['ridge_weather', 'forest_lags', 'forest_weather', 'persistence', 'seasonal_naive']
        np.testing.assert_allclose(a.iloc[:7][cols], b.iloc[:7][cols])
        self.assertTrue((a.Date > a.origin).all())

    def test_missing_targets_never_imputed_and_pairs_equal_across_models(self):
        frame = fixture()
        frame.loc[frame.index[-10], 'PM25'] = np.nan
        predictions, metrics = backtest(frame, test_days=20, horizon=7, trees=3)
        self.assertNotIn(frame.index[-10], predictions.Date.tolist())
        self.assertFalse(predictions.isna().any().any())
        self.assertTrue((metrics.groupby('horizon').n_forecasts.nunique() == 1).all())

    def test_imputation_fitted_only_on_training_features(self):
        frame = fixture()
        end = frame.index[-21]
        frame.loc[frame.index > end, 'temperature_c'] = 10000
        models, features, eligible, _ = fit_horizon(frame, end, 7, trees=3)
        mask = eligible & frame.PM25.shift(-7).notna() & (frame.index + pd.Timedelta(days=7) <= end)
        model, columns = models['forest_weather']
        statistic = model.steps[0][1].statistics_[columns.index('temperature_c')]
        self.assertEqual(statistic, features.loc[mask, 'temperature_c'].median())

    def test_baseline_alignment_and_refit_forecast_dates(self):
        frame = fixture()
        pred, _ = backtest(frame, test_days=20, trees=3)
        row = pred.loc[pred.horizon == 7].iloc[0]
        self.assertEqual(row.seasonal_naive, frame.loc[row.origin, 'PM25'])
        self.assertEqual(row.persistence, frame.loc[row.origin, 'PM25'])
        future = future_forecast(frame, trees=3)
        self.assertEqual(future.Date.iloc[0], frame.index[-1] + pd.Timedelta(days=1))
        self.assertEqual(len(future), 7)

    def test_calendar_gaps_and_mixed_stations_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'daily.csv'
            for kind in ('gap', 'duplicate', 'negative', 'infinite', 'mixed'):
                frame = fixture()
                if kind == 'gap': frame = frame.drop(frame.index[20])
                elif kind == 'duplicate': frame = pd.concat([frame, frame.iloc[[0]]])
                elif kind == 'negative': frame.iloc[0, 0] = -1
                elif kind == 'infinite': frame.iloc[0, 0] = np.inf
                else: frame.iloc[0, frame.columns.get_loc('naps_station_id')] = '060410'
                frame.to_csv(path)
                with self.subTest(kind=kind), self.assertRaises(ValueError): load_data(path)

    def test_reports_include_units_and_observed_pair_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'daily.csv'
            fixture().to_csv(path)
            output = Path(folder) / 'reports'
            run(path, output, test_days=20, trees=3)
            self.assertEqual({p.name for p in output.iterdir()},
                             {'backtest.csv', 'metrics.csv', 'forecast.csv', 'run.json',
                              'backtest.png', 'horizon_errors.png', 'monthly_metrics.csv'})
            metadata = json.loads((output / 'run.json').read_text())
            self.assertEqual(metadata['target'], 'PM25')
            self.assertEqual(metadata['training_samples_by_horizon']['7'], 120)
