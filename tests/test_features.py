"""Deterministic tests for feature availability, imputation scope and input validation."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from data_sources import WEATHER_FIELDS
from features import load_data, make_features
from workflow import fit


def fixture():
    n = 160
    frame = pd.DataFrame(
        {"PM25": 12 + np.sin(np.arange(n) / 4) * 5},
        index=pd.date_range("2023-10-01", periods=n, name="Date"),
    )
    for i, name in enumerate(WEATHER_FIELDS):
        frame[name] = np.arange(n) / 10 + i
    frame["naps_station_id"] = "060430"
    frame["climate_station_id"] = "6158731"
    return frame


class ForecastTests(unittest.TestCase):
    def test_features_reference_completed_origin_and_known_target_calendar(self):
        frame = fixture()
        f, _, _ = make_features(frame, 7)
        origin = frame.index[20]
        self.assertEqual(f.loc[origin, "pm25_lag_0"], frame.PM25.iloc[20])
        self.assertEqual(f.loc[origin, "pm25_lag_13"], frame.PM25.iloc[7])
        self.assertEqual(f.loc[origin, "temperature_c"], frame.temperature_c.iloc[20])
        self.assertAlmostEqual(
            f.loc[origin, "pm25_mean_7d"], frame.PM25.iloc[14:21].mean()
        )

    def test_imputation_fitted_only_on_training_features(self):
        frame = fixture().rename(columns={"PM25": "AQI"})
        end = frame.index[-21]
        frame.loc[frame.index > end, "temperature_c"] = 10000
        config = {"name": "forest_weather_5", "family": "forest_weather", "leaf": 5}
        model, features, columns, eligible, _, _ = fit(frame, end, 7, config)
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
