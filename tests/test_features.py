"""Deterministic tests for feature availability, imputation scope and input validation."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from airquality.sources import WEATHER_FIELDS
from airquality.features import load_data, make_features
from airquality.training import fit


def fixture():
    n = 160
    frame = pd.DataFrame(
        {"AQI": 12 + np.sin(np.arange(n) / 4) * 5},
        index=pd.date_range("2023-10-01", periods=n, name="Date"),
    )
    for i, name in enumerate(WEATHER_FIELDS):
        frame[name] = np.arange(n) / 10 + i
    # Same-day pollutant readings used by the richer feature sets.
    for i, name in enumerate(
        ("PM25_AQI", "PM25_max_1h", "O3_max_1h", "NO2_max_1h", "PM25_evening")
    ):
        frame[name] = 10 + np.cos(np.arange(n) / (3 + i)) * 4
    for name in ("O3_afternoon", "O3_AQI", "NO2_AQI"):
        frame[name] = 20 + np.sin(np.arange(n) / 5) * 3
    frame["naps_station_id"] = "060430"
    frame["climate_station_id"] = "6158731"
    return frame


class ForecastTests(unittest.TestCase):
    def test_features_reference_completed_origin_and_known_target_calendar(self):
        frame = fixture()
        f, _, _ = make_features(frame, 7)
        origin = frame.index[20]
        # AQI is available one day late: lag 0 is the day before the origin.
        self.assertEqual(f.loc[origin, "aqi_lag_0"], frame.AQI.iloc[19])
        self.assertEqual(f.loc[origin, "aqi_lag_13"], frame.AQI.iloc[6])
        self.assertEqual(f.loc[origin, "temperature_c"], frame.temperature_c.iloc[20])
        self.assertAlmostEqual(
            f.loc[origin, "aqi_mean_7d"], frame.AQI.iloc[13:20].mean()
        )

    def test_imputation_fitted_only_on_training_features(self):
        frame = fixture()
        end = frame.index[-21]
        frame.loc[frame.index > end, "temperature_c"] = 10000
        config = {"name": "ridge", "family": "ridge", "alpha": 1.0}
        model, features, eligible, _, _ = fit(frame, end, 7, config)
        columns = features.columns.tolist()
        # AQI labels become available one day late, so day D trains only if D+1 <= end.
        mask = (
            eligible
            & frame.AQI.shift(-7).notna()
            & (frame.index + pd.Timedelta(days=8) <= end)
        )
        statistic = model.steps[0][1].statistics_[columns.index("temperature_c")]
        self.assertEqual(statistic, features.loc[mask, "temperature_c"].median())

    def test_calendar_gaps_and_mixed_stations_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "daily.csv"
            for kind in ("gap", "duplicate", "negative", "infinite", "mixed"):
                frame = fixture()
                if kind == "gap":
                    frame = frame.drop(frame.index[20])
                elif kind == "duplicate":
                    frame = pd.concat([frame, frame.iloc[[0]]])
                elif kind == "negative":
                    frame.iloc[0, 0] = -1
                elif kind == "infinite":
                    frame.iloc[0, 0] = np.inf
                else:
                    frame.iloc[0, frame.columns.get_loc("naps_station_id")] = "060410"
                frame.to_csv(path)
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    load_data(path)
