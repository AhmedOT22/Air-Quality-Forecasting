"""Data freshness, safe fallback and real Streamlit interaction tests."""

import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from airquality.dashboard_data import (
    local_bundle,
    load_bundle,
    freshness,
    validate_bundle,
    observed_series,
)

try:
    import streamlit as st
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None

ROOT = Path(__file__).resolve().parents[1]


class DashboardDataTests(unittest.TestCase):
    def test_old_success_is_not_labelled_current(self):
        bundle = local_bundle()
        future = (bundle["forecast"].origin.max() + pd.Timedelta(days=30)).tz_localize(
            "UTC"
        )
        label, _ = freshness(bundle, now=future)
        self.assertEqual(label, "Historical snapshot")

    def test_failed_refresh_keeps_historical_forecast_visible(self):
        bundle = local_bundle()
        bundle["status"] = {
            "publication_status": "blocked",
            "attempted_at": "2026-10-31T12:00:00Z",
            "error": "Missing source data",
        }
        validate_bundle(bundle)
        label, reason = freshness(bundle, now="2026-10-31T13:00:00Z")
        self.assertEqual(label, "Refresh blocked")
        self.assertIn("Missing source", reason)

    def test_unavailable_published_data_falls_back_with_notice(self):
        with patch(
            "airquality.dashboard_data.published_bundle",
            side_effect=OSError("network unavailable"),
        ):
            bundle = load_bundle(True)
        self.assertEqual(bundle["source"], "Bundled snapshot")
        self.assertTrue(any("bundled snapshot" in w for w in bundle["warnings"]))

    def test_published_reports_prefer_data_branch_then_main(self):
        from airquality import dashboard_data as dashboard_data

        requested = []

        def fake_request(url):
            requested.append(url)
            if url.endswith("/heads/data"):
                raise OSError("no data branch yet")
            raise OSError("stop after branch resolution")

        with patch("airquality.dashboard_data.request", side_effect=fake_request):
            with self.assertRaises(OSError):
                dashboard_data.published_bundle()
        self.assertTrue(requested[0].endswith("/git/ref/heads/data"))
        self.assertTrue(requested[1].endswith("/git/ref/heads/main"))

    def test_latest_model_version_is_displayed_without_merging_issuances(self):
        bundle = local_bundle()
        old = bundle["forecast"].copy()
        new = old.copy()
        new["model_id"] = "new-version"
        new["issued_at"] = (
            pd.to_datetime(old.issued_at, utc=True, format="ISO8601").max()
            + pd.Timedelta(hours=1)
        ).isoformat()
        new["predicted_AQI"] = new.predicted_AQI + 1
        bundle["forecast"] = pd.concat([old, new], ignore_index=True)
        result = validate_bundle(bundle)["forecast"]
        self.assertEqual(len(result), len(old))
        self.assertTrue(result.model_id.eq("new-version").all())

    def test_duplicate_and_invalid_forecast_dates_are_rejected(self):
        bundle = local_bundle()
        for kind in ["duplicate", "past"]:
            changed = copy.deepcopy(bundle)
            if kind == "duplicate":
                changed["forecast"] = pd.concat(
                    [changed["forecast"], changed["forecast"].iloc[[0]]]
                )
            else:
                changed["forecast"].iloc[
                    0, changed["forecast"].columns.get_loc("Date")
                ] = changed["forecast"].origin.iloc[0]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate_bundle(changed)

    def test_nonfinite_predictions_and_incomplete_or_mismatched_horizons_are_rejected(
        self,
    ):
        bundle = local_bundle()
        for kind in ["infinite", "missing", "wrong_horizon"]:
            changed = copy.deepcopy(bundle)
            if kind == "infinite":
                changed["forecast"].iloc[
                    0, changed["forecast"].columns.get_loc("predicted_AQI")
                ] = np.inf
            elif kind == "missing":
                changed["forecast"] = changed["forecast"].iloc[1:]
            else:
                changed["forecast"].iloc[
                    0, changed["forecast"].columns.get_loc("horizon")
                ] = 7
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate_bundle(changed)

    def test_observed_history_revisions_replace_dates_and_keep_calendar_gaps(self):
        history = pd.DataFrame(
            {"Date": pd.to_datetime(["2026-01-01", "2026-01-02"]), "AQI": [20.0, 30.0]}
        )
        bundle = {
            "observations": pd.DataFrame(
                {"Date": ["2026-01-02", "2026-01-04"], "AQI": [35.0, 50.0]}
            )
        }
        series = observed_series(bundle, history)
        self.assertEqual(len(series), 4)
        self.assertEqual(series.AQI.iloc[1], 35.0)
        self.assertTrue(pd.isna(series.AQI.iloc[2]))

    def test_future_refresh_timestamp_is_not_current(self):
        bundle = local_bundle()
        now = (
            bundle["forecast"].origin.iloc[0] + pd.Timedelta(days=1, hours=12)
        ).tz_localize("Etc/GMT+5")
        bundle["status"]["publication_status"] = "current"
        bundle["status"]["attempted_at"] = (now + pd.Timedelta(hours=1)).isoformat()
        self.assertEqual(freshness(bundle, now)[0], "Historical snapshot")


@unittest.skipIf(
    AppTest is None, "Install requirements.txt for Streamlit integration tests"
)
class DashboardUITests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"AQI_DASHBOARD_OFFLINE": "1"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        st.cache_data.clear()

    def app(self):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
        self.assertFalse(app.exception, [e.message for e in app.exception])
        return app

    def test_default_dashboard_and_horizon_and_challenger_controls(self):
        app = self.app()
        self.assertEqual(len(app.metric), 6)  # four headline cards, two alert scores
        self.assertEqual(
            [t.label for t in app.tabs],
            ["Outlook", "Observed history", "How reliable is it?", "About the model"],
        )
        app.slider[0].set_value(3).run()
        app.toggle[1].set_value(True).run()
        app.toggle[0].set_value(False).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe[0].value), 3)

    def test_empty_live_scores_are_not_presented_as_zero_error(self):
        bundle = local_bundle()
        bundle["metrics"] = pd.DataFrame()
        bundle["status"]["prospective_scores"] = 0
        with patch("airquality.dashboard_data.load_bundle", return_value=bundle):
            app = self.app()
        self.assertTrue(
            any("Waiting for observed outcomes" in info.value for info in app.info)
        )
        self.assertTrue(any("likely range held" in c.value for c in app.caption))
        app.selectbox[0].select("All data since 2020").run()
        app.selectbox[1].select("Ozone").run()
        self.assertFalse(app.exception)

    def test_live_accuracy_is_hidden_until_enough_scored_pairs(self):
        bundle = local_bundle()
        bundle["metrics"] = bundle["metrics"].assign(n=5)
        with patch("airquality.dashboard_data.load_bundle", return_value=bundle):
            app = self.app()
        self.assertTrue(any("of 30 scored forecasts" in i.value for i in app.info))
        self.assertFalse(
            any("Detailed prospective scores" in e.label for e in app.expander)
        )

    def test_prospective_performance_visuals_render_once_mature(self):
        bundle = local_bundle()
        self.assertFalse(bundle["metrics"].empty)
        bundle["metrics"] = bundle["metrics"].assign(n=30)
        with patch("airquality.dashboard_data.load_bundle", return_value=bundle):
            app = self.app()
        self.assertTrue(
            any("Detailed prospective scores" in e.label for e in app.expander)
        )

    def test_model_drivers_chart_switches_horizon(self):
        app = self.app()
        self.assertTrue(any("Importance by horizon" in e.label for e in app.expander))
        app.select_slider[0].set_value(7).run()
        self.assertFalse(app.exception)

    def test_blocked_refresh_is_visible_without_crashing(self):
        bundle = local_bundle()
        bundle["status"]["publication_status"] = "blocked"
        bundle["status"]["error"] = "Provider is unavailable"
        with patch("airquality.dashboard_data.load_bundle", return_value=bundle):
            # app imports the function at execution time.
            app = self.app()
        self.assertTrue(any("Refresh blocked" in w.value for w in app.warning))
        self.assertFalse(app.exception)

    def test_outlook_shows_chances_and_guidance_for_each_day(self):
        app = self.app()
        table = app.dataframe[0].value
        self.assertIn("Chance above 50", table)
        self.assertTrue(table["Chance above 50"].between(0, 100).all())
        self.assertTrue(table["What to do"].str.len().gt(0).all())
        self.assertTrue(any("Chance above 50" in m.label for m in app.metric))

    def test_ledger_from_before_the_model_release_still_renders(self):
        bundle = local_bundle()
        forecast = bundle["forecast"]
        bundle["forecast"] = forecast.assign(
            model=forecast.model.replace(forecast.model.iloc[0], "ridge_1")
        ).drop(columns=["p_moderate", "p_unhealthy_sensitive"])
        with patch("airquality.dashboard_data.load_bundle", return_value=bundle):
            app = self.app()
        self.assertTrue(
            any("predates the current model" in w.value for w in app.warning)
        )
        self.assertNotIn("Chance above 50", app.dataframe[0].value)
