"""Operational guards, immutable issuance and delayed prospective scoring."""

import unittest
import numpy as np
import pandas as pd
from tests.test_forecast import fixture
from operations import HISTORY_COLUMNS, OBS_COLUMNS, freshness, issue, observe, score

CONFIG = {"name": "persistence", "family": "persistence"}


def example():
    f = fixture().rename(columns={"PM25": "AQI"})
    f.index = pd.date_range("2026-05-25", periods=len(f), name="Date")
    f["verification_status"] = "includes_unverified_observations"
    return f


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.frame = example()
        self.origin = self.frame.index[-1]
        self.now = (self.origin + pd.Timedelta(days=1, hours=10)).tz_localize(
            "Etc/GMT+5"
        )
        self.history = pd.DataFrame(columns=HISTORY_COLUMNS)
        self.observations = pd.DataFrame(columns=OBS_COLUMNS)

    def test_first_issuance_immutable_and_same_day_marked(self):
        history, new = issue(
            self.frame, CONFIG, {"input_sha256": "a"}, self.now, self.history, "code"
        )
        self.assertEqual(len(new), 7)
        self.assertEqual(
            new.evaluation_type.tolist(), ["same_day"] + ["prospective"] * 6
        )
        changed = self.frame.copy()
        changed.AQI *= 2
        again, issued = issue(
            changed, CONFIG, {"input_sha256": "b"}, self.now, history, "code"
        )
        self.assertTrue(issued.empty)
        pd.testing.assert_frame_equal(history, again)

    def test_freshness_rejects_old_origin_weather_gaps_stale_hours_and_missing_lags(
        self,
    ):
        manifest = {
            "latest_pollution_hour_est": str(
                self.now.tz_localize(None) - pd.Timedelta(hours=2)
            )
        }
        freshness(self.frame, manifest, self.now)
        cases = []
        cases.append((self.frame.iloc[:-1], manifest))
        weather = self.frame.copy()
        weather.iloc[-1, weather.columns.get_loc("temperature_c")] = np.nan
        cases.append((weather, manifest))
        missing = self.frame.copy()
        missing.iloc[-2, missing.columns.get_loc("AQI")] = np.nan
        cases.append((missing, manifest))
        cases.append((self.frame, {"latest_pollution_hour_est": str(self.origin)}))
        for frame, metadata in cases:
            with self.assertRaises(ValueError):
                freshness(frame, metadata, self.now)

    def test_no_score_until_observation_matures_and_no_historical_performance(self):
        history, _ = issue(
            self.frame, CONFIG, {"input_sha256": "a"}, self.now, self.history, "code"
        )
        f = self.frame.reindex(
            pd.date_range(self.frame.index[0], self.origin + pd.Timedelta(days=8))
        )
        f["AQI"] = 30.0
        f["verification_status"] = "provisional"
        observations = observe(f, {"input_sha256": "b"}, self.now, self.observations)
        scores, metrics = score(history, observations)
        self.assertTrue(scores.empty)
        self.assertTrue(metrics.empty)
        later = self.now + pd.Timedelta(days=4)
        observations = observe(f, {"input_sha256": "b"}, later, observations)
        scores, metrics = score(history, observations)
        self.assertEqual(len(scores), 2)  # horizons 2/3 mature; same-day h1 excluded
        self.assertEqual(set(scores.horizon), {2, 3})
        self.assertTrue((scores.actual_first == 30).all())
        self.assertTrue((metrics.n == 1).all())

    def test_truth_revisions_keep_first_and_record_return_to_prior_value(self):
        f = self.frame.iloc[:3].copy()
        f.AQI = 30.0
        previous = observe(f, {"input_sha256": "a"}, self.now, self.observations)
        f.AQI = 40.0
        previous = observe(
            f, {"input_sha256": "b"}, self.now + pd.Timedelta(hours=1), previous
        )
        f.AQI = 30.0
        previous = observe(
            f, {"input_sha256": "c"}, self.now + pd.Timedelta(hours=2), previous
        )
        self.assertEqual(len(previous), 9)
        self.assertTrue(
            (previous.drop_duplicates("Date", keep="first").AQI == 30).all()
        )
        self.assertTrue((previous.drop_duplicates("Date", keep="last").AQI == 30).all())
        again = observe(
            f, {"input_sha256": "d"}, self.now + pd.Timedelta(hours=3), previous
        )
        self.assertEqual(len(again), len(previous))

    def test_scoring_accepts_mixed_iso_timestamp_precision(self):
        history, _ = issue(
            self.frame, CONFIG, {"input_sha256": "a"}, self.now, self.history, "code"
        )
        future = self.frame.reindex(
            pd.date_range(self.frame.index[0], self.origin + pd.Timedelta(days=8))
        )
        future["AQI"] = 30.0
        future["verification_status"] = "provisional"
        observations = observe(
            future,
            {"input_sha256": "b"},
            self.now + pd.Timedelta(days=8),
            self.observations,
        )
        history.loc[1, "issued_at"] = (
            self.now + pd.Timedelta(microseconds=123)
        ).isoformat()
        observations.loc[observations.index[-2], "first_seen_at"] = (
            self.now + pd.Timedelta(days=8, microseconds=456)
        ).isoformat()
        scores, metrics = score(history, observations)
        self.assertEqual(len(scores), 6)
        self.assertEqual(int(metrics.n.sum()), 6)

    def test_real_issuance_clock_is_read_after_inference(self):
        from unittest.mock import patch
        from workflow import forward

        events = []

        def predict(frame, config):
            events.append("predict")
            return forward(frame, config)

        def clock(value):
            events.append("clock")
            return self.now.tz_convert("UTC")

        with (
            patch("operations.forward", side_effect=predict),
            patch("operations.utc", side_effect=clock),
        ):
            issue(self.frame, CONFIG, {"input_sha256": "a"}, None, self.history, "code")
        self.assertEqual(events, ["predict", "clock"])

    def test_monitor_needs_samples_and_detects_deterioration(self):
        from operations import monitor

        rows = pd.DataFrame(
            {
                "model": ["ridge"] * 60,
                "model_id": ["v1"] * 60,
                "horizon": [2] * 60,
                "Date": pd.date_range("2026-01-01", periods=60).strftime("%Y-%m-%d"),
                "model_abs_error": [1.0] * 30 + [4.0] * 30,
                "persistence_abs_error": [2.0] * 60,
            }
        )
        rolling, alerts = monitor(rows)
        self.assertEqual(rolling.MAE.iloc[0], 4.0)
        self.assertEqual(len(alerts["alerts"]), 2)
        _, small = monitor(rows.tail(10))
        self.assertFalse(small["alerts"])

    def test_failed_validation_preserves_previous_forecast_and_marks_blocked(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from operations import run

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            previous = path / "latest_forecast.csv"
            previous.write_text("previous forecast remains historical\n")
            with patch(
                "operations.validate", side_effect=ValueError("changed release")
            ):
                with self.assertRaises(ValueError):
                    run(refresh=False, now=self.now, reports=path)
            self.assertEqual(
                previous.read_text(), "previous forecast remains historical\n"
            )
            status = json.loads((path / "status.json").read_text())
            self.assertEqual(status["publication_status"], "blocked")
            self.assertIn("changed release", status["error"])
