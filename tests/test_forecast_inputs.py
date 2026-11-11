"""Forecast inputs, the leak guard on observed stand-ins, decisions and extra weather."""

import unittest
import numpy as np
import pandas as pd
from airquality import decisions
from airquality.features import build_features
from airquality.forecast_inputs import VARIABLES, ForecastInputs, cams_daily, daily
from airquality.operations import model_identity
from airquality.sources import weather_daily
from airquality.uncertainty import residual_width, attach
from tests.test_features import fixture


class ForecastAdditionsTests(unittest.TestCase):
    def test_residual_quantile_uses_finite_sample_rank_and_nonnegative_bounds(self):
        self.assertEqual(residual_width(np.arange(1, 101), 0.90), 91)
        with self.assertRaises(ValueError):
            residual_width([1, 2])
        result = attach(
            pd.DataFrame({"horizon": [1], "predicted_AQI": [5.0]}),
            pd.DataFrame(
                {"horizon": [1], "half_width": [10.0], "nominal_coverage": [0.9]}
            ),
        )
        self.assertEqual(result.lower_AQI.iloc[0], 0.0)
        self.assertEqual(result.upper_AQI.iloc[0], 15.0)

    def test_forecast_units_precision_coverage_and_timezone(self):
        hours = pd.date_range("2026-01-01", periods=24, freq="h")
        data = {
            "utc_offset_seconds": -18000,
            "hourly": {"time": hours.astype(str).tolist()},
            "hourly_units": {},
        }
        for variable, unit in zip(VARIABLES.values(), ["°C", "%", "km/h", "hPa"]):
            data["hourly"][variable] = [1000.0] * 24
            data["hourly_units"][variable] = unit
        result = daily(data)
        self.assertEqual(result.pressure_kpa.iloc[0], 100.0)
        data["hourly"]["temperature_2m"][:7] = [None] * 7
        self.assertTrue(np.isnan(daily(data).temperature_c.iloc[0]))
        data["utc_offset_seconds"] = 0
        with self.assertRaises(ValueError):
            daily(data)

    def inputs(self, frame, start="2020-01-01", leads=(1, 7)):
        dates = pd.date_range(start, frame.index[-1] + pd.Timedelta(days=8))
        rows = [
            {"Date": d, "horizon": h, **{n: float(d.day + h * 100) for n in VARIABLES}}
            for h in leads
            for d in dates
        ]
        cams = pd.DataFrame(
            {
                "cams_pm25": 5.0,
                "cams_pm25_max": 9.0,
                "cams_o3_max": 60.0,
                "cams_aod": 0.1,
            },
            index=pd.DatetimeIndex(dates, name="Date"),
        )
        return ForecastInputs(pd.DataFrame(rows), cams)

    def test_forecast_features_use_the_target_day_and_matching_lead(self):
        frame = fixture()
        inputs = self.inputs(frame)
        x, _, valid, required = build_features(frame, 7, "forecast", inputs)
        origin = frame.index[25]
        self.assertEqual(
            x.loc[origin, "forecast_temperature_c"],
            float((origin + pd.Timedelta(days=7)).day + 700),
        )
        self.assertTrue(valid.loc[origin])
        self.assertIn("forecast_temperature_c", required)
        # A forecast missing for the target day makes the origin unusable.
        inputs.weather[7] = inputs.weather[7].drop(origin + pd.Timedelta(days=7))
        _, _, valid, _ = build_features(frame, 7, "forecast", inputs)
        self.assertFalse(valid.loc[origin])

    def test_observed_stand_in_never_reaches_rows_after_the_fit_window(self):
        frame = fixture()  # 2023-10-01 onward; the forecast archive starts in 2024
        inputs = self.inputs(frame, start="2024-01-01", leads=(1,))
        fit_end = pd.Timestamp("2023-12-10")
        x, _, valid, _ = build_features(frame, 1, "forecast", inputs, fit_end=fit_end)
        inside = pd.Timestamp("2023-12-01")  # target Dec 2 <= fit_end: observed weather
        self.assertEqual(
            x.loc[inside, "forecast_temperature_c"],
            frame.temperature_c.loc[inside + pd.Timedelta(days=1)],
        )
        after = pd.Timestamp("2023-12-15")  # target after fit_end, before the archive
        self.assertTrue(np.isnan(x.loc[after, "forecast_temperature_c"]))
        self.assertFalse(valid.loc[after])
        # Without a fit window (forecasting), observed weather is never substituted.
        x, _, _, _ = build_features(frame, 1, "forecast", inputs)
        self.assertTrue(np.isnan(x.loc[inside, "forecast_temperature_c"]))
        # Changing observed weather after the fit window cannot alter any feature.
        changed = frame.copy()
        changed.loc[changed.index > fit_end, "temperature_c"] = 9999
        again, _, _, _ = build_features(changed, 1, "forecast", inputs, fit_end=fit_end)
        pd.testing.assert_series_equal(
            x.forecast_temperature_c.loc[: fit_end - pd.Timedelta(days=1)].iloc[:0],
            again.forecast_temperature_c.iloc[:0],
        )
        np.testing.assert_array_equal(
            build_features(frame, 1, "forecast", inputs, fit_end=fit_end)[
                0
            ].forecast_temperature_c.to_numpy(),
            again.forecast_temperature_c.to_numpy(),
        )

    def test_cams_summaries_and_five_day_reach(self):
        hours = pd.date_range("2026-01-01", periods=48, freq="h")
        payload = {
            "utc_offset_seconds": -18000,
            "hourly": {
                "time": hours.astype(str).tolist(),
                "pm2_5": [4.0] * 24 + [10.0] * 23 + [40.0],
                "ozone": [50.0] * 48,
                "aerosol_optical_depth": [0.2] * 48,
            },
            "hourly_units": {
                "pm2_5": "μg/m³",
                "ozone": "μg/m³",
                "aerosol_optical_depth": "",
            },
        }
        table = cams_daily(payload)
        self.assertEqual(table.cams_pm25.iloc[0], 4.0)
        self.assertEqual(table.cams_pm25_max.iloc[1], 40.0)
        payload["hourly_units"]["pm2_5"] = "ppb"
        with self.assertRaises(ValueError):
            cams_daily(payload)
        frame = fixture()
        inputs = self.inputs(frame, leads=(5, 6))
        near, _, _, _ = build_features(frame, 5, "forecast_cams", inputs)
        far, _, _, _ = build_features(frame, 6, "forecast_cams", inputs)
        self.assertEqual(near.cams_pm25.iloc[30], 5.0)
        self.assertTrue(far.cams_pm25.isna().all())

    def test_live_forecasts_fill_only_days_after_the_origin(self):
        frame = fixture()
        inputs = self.inputs(frame)
        origin = frame.index[-1]
        target = origin + pd.Timedelta(days=1)
        live = pd.DataFrame(
            {name: 1.5 for name in VARIABLES}, index=pd.DatetimeIndex([target])
        )
        updated = inputs.with_live(origin, live, None)
        self.assertEqual(updated.weather_for([target], 1).temperature_c.iloc[0], 1.5)
        self.assertEqual(
            inputs.weather_for([target], 1).temperature_c.iloc[0],
            float(target.day + 100),
        )

    def test_exceedance_probability_and_alert_cutoff(self):
        errors = np.linspace(-20, 20, 41)  # 20 errors above zero, 20 below
        self.assertAlmostEqual(decisions.exceedance(50, errors, 50), 20.5 / 42)
        self.assertLess(decisions.exceedance(10, errors, 50), 0.02)
        self.assertGreater(decisions.exceedance(90, errors, 50), 0.98)
        with self.assertRaises(ValueError):
            decisions.exceedance(50, errors[:5], 50)
        dates = pd.date_range("2025-01-01", periods=10)
        rows = pd.DataFrame(
            {
                "Date": dates,
                "horizon": 1,
                "p_moderate": [0.9, 0.8, 0.6, 0.4, 0.3, 0.2, 0.1, 0.1, 0.1, 0.1],
                "is_moderate": [True, True, True, False, True, False] + [False] * 4,
            }
        )
        table = decisions.alert_table(rows, "moderate")
        half = table.loc[table.cutoff.eq(0.5)].iloc[0]
        self.assertEqual((half.hits, half.misses, half.false_alarms), (3, 1, 0))
        # 0.5 catches 75% with no false alarm; lower cut-offs only add false alarms.
        self.assertEqual(decisions.choose_cutoff(table, "moderate", year=2025), 0.5)

    def test_extra_weather_wind_vector_and_smoke_hours(self):
        hours = pd.date_range("2026-01-01", periods=24, freq="h")
        features = []
        for i, stamp in enumerate(hours):
            properties = {"CLIMATE_IDENTIFIER": "6158731", "LOCAL_DATE": str(stamp)}
            values = {
                "TEMP": 1.0,
                "RELATIVE_HUMIDITY": 50,
                "WIND_SPEED": 10,
                "STATION_PRESSURE": 100.0,
                "DEW_POINT_TEMP": -2.0,
                "VISIBILITY": 24.1 if i else 3.0,
                "WIND_DIRECTION": 27,  # wind from the west
            }
            for name, value in values.items():
                properties[name] = value
                properties[name + "_FLAG"] = None
            properties["WEATHER_ENG_DESC"] = "Smoke" if i < 5 else "Clear"
            features.append({"properties": properties})
        day = weather_daily({"features": features}, "6158731").iloc[0]
        self.assertAlmostEqual(day.wind_u_kmh, 10.0)  # blowing toward the east
        self.assertAlmostEqual(day.wind_v_kmh, 0.0, places=6)
        self.assertEqual(day.visibility_min_km, 3.0)
        self.assertEqual(day.smoke_hours, 5)
        self.assertEqual(day.haze_hours, 0)

    def test_model_identity_depends_on_configuration_not_on_source_files(self):
        config = {"name": "m", "family": "boosting", "leaf": 10, "features": "forecast"}
        self.assertEqual(model_identity(config), model_identity(dict(config)))
        self.assertNotEqual(
            model_identity(config), model_identity(dict(config, leaf=20))
        )
