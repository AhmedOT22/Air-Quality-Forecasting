"""AQI reference examples, window definitions and availability boundary tests."""

import unittest

import numpy as np
import pandas as pd

from airquality.aqi import (
    concentration_index,
    daily_aqi,
    no2_index,
    ozone_index,
    pm25_index,
    so2_index,
)
from airquality.features import make_features, seasonal_lag
from tests.test_features import fixture
from airquality.training import evaluate


def hourly_fixture():
    frame = pd.DataFrame(
        0.0,
        index=pd.date_range("2023-12-30", periods=96, freq="h"),
        columns=["PM25", "O3", "NO2", "SO2"],
    )
    frame.PM25 = 12
    frame.O3 = 54
    return frame


class AQITests(unittest.TestCase):
    def test_epa_worked_examples_and_half_up_rounding(self):
        self.assertEqual(ozone_index(78.53333, 104), 126)
        self.assertEqual(pm25_index(35.9), 102)
        # The guidance's printed 148 for 0.162 ppm is an arithmetic typo:
        # its table/equation gives 101 + 49 * 37 / 39 = 147.487..., rounded 147.
        self.assertEqual(ozone_index(78, 162), 147)
        self.assertEqual(concentration_index(1, [(0, 2)], [(0, 1)], 0), 1)

    def test_breakpoint_versions_and_truncation(self):
        self.assertEqual(pm25_index(12, "epa_2018"), 50)
        self.assertEqual(pm25_index(12.1, "epa_2018"), 51)
        self.assertEqual(pm25_index(9.09, "epa_2024"), 50)
        self.assertEqual(pm25_index(9.1, "epa_2024"), 51)
        self.assertEqual(pm25_index(500.4, "epa_2018"), 500)
        self.assertEqual(pm25_index(325.4, "epa_2024"), 500)
        self.assertGreater(pm25_index(800), 500)
        self.assertEqual(no2_index(53.9), 50)
        # EPA's published 2024 table, including the combined hazardous band.
        for concentration, expected in [
            (0, 0),
            (9, 50),
            (9.1, 51),
            (35.4, 100),
            (35.5, 101),
            (55.4, 150),
            (55.5, 151),
            (125.4, 200),
            (125.5, 201),
            (225.4, 300),
            (225.5, 301),
            (325.4, 500),
        ]:
            with self.subTest(concentration=concentration):
                self.assertEqual(pm25_index(concentration), expected)

    def test_2024_defaults_recompute_components_categories_and_dominance(self):
        frame = hourly_fixture()
        frame.PM25 = 12
        frame.O3 = 0
        frame.NO2 = 53
        current = daily_aqi(frame).loc["2023-12-31"]
        legacy = daily_aqi(frame, "epa_2018").loc["2023-12-31"]
        self.assertEqual(pm25_index(12), 56)
        self.assertEqual(current.aqi_standard, "epa_2024")
        self.assertEqual(current.PM25_AQI, 56)
        self.assertEqual(current.AQI, 56)
        self.assertEqual(current.AQI_category, "Moderate")
        self.assertEqual(current.dominant_pollutant, "PM25")
        self.assertEqual(legacy.AQI, 50)
        self.assertEqual(legacy.AQI_category, "Good")
        self.assertEqual(legacy.dominant_pollutant, "PM25|NO2")
        self.assertEqual(current.aqi_available_after, legacy.aqi_available_after)

    def test_so2_uses_peak_at_low_values_and_daily_mean_at_high_values(self):
        self.assertEqual(so2_index(304, 20), 200)
        self.assertEqual(so2_index(305, 20), 200)
        self.assertEqual(so2_index(700, 305), 201)
        self.assertTrue(np.isnan(so2_index(np.nan, 20)))

    def test_daily_combination_uses_all_four_components(self):
        frame = hourly_fixture()
        frame.loc["2023-12-31 12:00", "NO2"] = 200
        result = daily_aqi(frame)
        row = result.loc["2023-12-31"]
        self.assertEqual(row.NO2_AQI, no2_index(200))
        self.assertEqual(row.AQI, row.NO2_AQI)
        self.assertEqual(row.dominant_pollutant, "NO2")
        self.assertEqual(row.AQI_components_available, 4)

    def test_missing_component_cannot_reduce_combined_aqi(self):
        frame = hourly_fixture()
        frame.loc["2023-12-31", "SO2"] = np.nan
        result = daily_aqi(frame)
        self.assertTrue(np.isnan(result.loc["2023-12-31", "AQI"]))
        self.assertEqual(result.loc["2023-12-31", "AQI_components_available"], 3)

    def test_ozone_windows_cross_midnight_and_incomplete_tail_is_missing(self):
        frame = hourly_fixture()
        frame.O3 = 0
        frame.loc["2024-01-01 00:00":"2024-01-01 06:00", "O3"] = 160
        result = daily_aqi(frame)
        self.assertGreater(result.loc["2023-12-31", "O3_max_8h_ppb"], 100)
        self.assertEqual(
            result.loc["2023-12-31", "aqi_available_after"], pd.Timestamp("2024-01-01")
        )
        self.assertTrue(np.isnan(result.AQI.iloc[-1]))

    def test_aqi_current_day_is_not_used_before_ozone_is_finalized(self):
        frame = fixture()
        f, _, _ = make_features(frame, 1)
        self.assertEqual(f.aqi_lag_0.iloc[20], frame.AQI.iloc[19])
        changed = frame.copy()
        changed.loc[changed.index[-21] :, "AQI"] = 999
        boundary = frame.index[-21]
        configs = [
            {"name": "ridge_1", "family": "ridge", "alpha": 1.0},
            {"name": "persistence", "family": "persistence"},
            {"name": "weekly", "family": "weekly"},
        ]
        a, _ = evaluate(frame, boundary, frame.index[-1], configs)
        b, _ = evaluate(changed, boundary, frame.index[-1], configs)
        first = a.origin.eq(boundary)
        np.testing.assert_allclose(a.loc[first, "predicted"], b.loc[first, "predicted"])
        self.assertEqual(seasonal_lag(7, 1), 7)
        persistence = a.loc[
            first & a.model.eq("persistence") & a.horizon.eq(1), "predicted"
        ].iloc[0]
        self.assertEqual(persistence, frame.AQI.iloc[-22])

    def test_gas_export_without_method_and_unpadded_station(self):
        from airquality.naps_aqi import read_hourly
        import csv, io

        stream = io.StringIO()
        stream.write("Units, ppb\nNote,Data is hour ending local standard time\n")
        writer = csv.writer(stream)
        columns = ["Pollutant", "NAPS ID", "Latitude", "Longitude", "Date"] + [
            f"H{h:02d}" for h in range(1, 25)
        ]
        writer.writerow([f"{c}//{c}" for c in columns])
        writer.writerow(
            ["O3", "60430", "43.7094", "-79.5435", "2024-01-01"] + [10] * 24
        )
        hourly, metadata = read_hourly(stream.getvalue().encode(), "O3")
        self.assertEqual(len(hourly), 24)
        self.assertTrue((hourly == 10).all())
        self.assertEqual(metadata["methods"], ["not supplied in gas export"])
