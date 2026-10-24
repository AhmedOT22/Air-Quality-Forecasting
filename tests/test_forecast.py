"""Small deterministic fixtures test evaluation behavior, not Toronto accuracy."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from forecast import backtest, feature_row, fit_model, load_series, recursive_forecast, run


def series():
    return pd.Series(30 + np.sin(np.arange(90) / 3) * 5,
                     index=pd.date_range('2024-01-01', periods=90), name='AQI')


class ForecastTests(unittest.TestCase):
    def test_features_use_previous_days_and_calendar(self):
        history = np.arange(20, dtype=float)
        self.assertEqual(feature_row(history, '2024-02-01')[:5], [19, 18, 17, 13, 6])

    def test_future_labels_cannot_change_first_forecast(self):
        original = series()
        changed = original.copy()
        changed.iloc[-14:] = 999
        a, _ = backtest(original, test_days=14, horizon=7, trees=5)
        b, _ = backtest(changed, test_days=14, horizon=7, trees=5)
        # The entire first seven-day trajectory must be independent of holdout labels.
        np.testing.assert_allclose(a.iloc[:7]['random_forest'], b.iloc[:7]['random_forest'])
        self.assertTrue((a['Date'] > a['origin']).all())

    def test_recursion_includes_month_boundary(self):
        data = series().iloc[:31]
        predictions = recursive_forecast(fit_model(data, trees=5), data, 7)
        self.assertEqual(predictions.index[0], pd.Timestamp('2024-02-01'))
        self.assertEqual(len(predictions), 7)

    def test_baselines_and_horizon_counts(self):
        data = series()
        predictions, metrics = backtest(data, test_days=14, horizon=7, trees=5)
        self.assertEqual(len(predictions), 8 * 7)
        self.assertEqual(len(metrics), 3 * 7)
        self.assertTrue((metrics['n_forecasts'] == 8).all())
        self.assertEqual(predictions.iloc[0]['persistence'], data.iloc[-15])
        self.assertEqual(predictions.iloc[6]['seasonal_naive'], data.iloc[-15])

    def test_invalid_data_rejected_and_outputs_written(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'input.csv'
            data = series().rename_axis('Date').reset_index()
            for invalid in (data.iloc[1:].iloc[::2], pd.concat([data, data.iloc[:1]]),
                            data.assign(AQI=np.nan), data.assign(AQI=-1)):
                invalid.to_csv(path, index=False)
                with self.assertRaises(ValueError):
                    load_series(path)
            data.to_csv(path, index=False)
            output = Path(folder) / 'reports'
            run(path, output, test_days=14, trees=5)
            self.assertEqual({p.name for p in output.iterdir()},
                             {'backtest.csv', 'metrics.csv', 'forecast.csv', 'run.json', 'backtest.png'})
            self.assertEqual(len(pd.read_csv(output / 'forecast.csv')), 7)


if __name__ == '__main__':
    unittest.main()
