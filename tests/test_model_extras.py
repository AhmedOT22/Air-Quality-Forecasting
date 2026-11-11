"""Boosting candidate, rolling conformal widths and permutation-importance checks."""

import tempfile
import unittest
import unittest.mock
from pathlib import Path
import numpy as np
import pandas as pd
from airquality.explain import groups, importance
from tests.test_features import fixture
from airquality.uncertainty import (
    MIN_RESIDUALS,
    load_residuals,
    trailing_widths,
    window_errors,
)
from airquality.training import CANDIDATES, evaluate, tuning_grid


def residuals(start="2026-01-01", days=400, error=None):
    dates = pd.date_range(start, periods=days)
    rows = [
        {
            "Date": d,
            "horizon": h,
            "error": float(i if error is None else error),
            "abs_error": float(i if error is None else error),
        }
        for h in range(1, 8)
        for i, d in enumerate(dates)
    ]
    return pd.DataFrame(rows)


class BoostingTests(unittest.TestCase):
    def test_boosting_is_a_tunable_candidate_that_respects_the_boundary(self):
        boosting = next(c for c in CANDIDATES if c["family"] == "boosting")
        self.assertEqual([c["leaf"] for c in tuning_grid(boosting)], [10, 20, 40])
        frame = fixture()
        frame.loc[frame.index[50:60], "temperature_c"] = np.nan  # native NaN handling
        boundary = frame.index[100]
        changed = frame.copy()
        changed.loc[changed.index > boundary, "AQI"] = 900
        config = dict(boosting, leaf=5)
        a, _ = evaluate(frame, boundary, frame.index[-1], [config], horizons=[1])
        b, _ = evaluate(changed, boundary, frame.index[-1], [config], horizons=[1])
        first = a.origin.eq(boundary)
        np.testing.assert_allclose(a.loc[first, "predicted"], b.loc[first, "predicted"])


class RollingConformalTests(unittest.TestCase):
    def test_window_uses_only_errors_known_before_the_origin(self):
        table = residuals()
        origin = pd.Timestamp("2026-08-01")
        errors = window_errors(table, origin, 1, window=180)
        known = table.loc[table.horizon.eq(1) & (table.Date < origin)]
        expected = known.loc[known.Date >= origin - pd.Timedelta(days=180)]
        np.testing.assert_array_equal(errors, expected.abs_error.to_numpy())
        # Errors on or after the origin can never widen or narrow the interval.
        late = table.copy()
        late.loc[late.Date >= origin, "abs_error"] = 1e6
        np.testing.assert_array_equal(window_errors(late, origin, 1, 180), errors)

    def test_stale_window_falls_back_to_most_recent_errors(self):
        table = residuals(days=100)
        errors = window_errors(table, pd.Timestamp("2027-06-01"), 3, window=180)
        self.assertEqual(len(errors), 100)
        self.assertGreaterEqual(len(errors), MIN_RESIDUALS)
        with self.assertRaises(ValueError):
            trailing_widths(residuals(days=10), pd.Timestamp("2026-03-01"))

    def test_widths_use_the_conformal_rank_per_horizon(self):
        table = residuals(days=99, error=None)
        widths = trailing_widths(table, pd.Timestamp("2026-04-10"), window=180)
        self.assertEqual(widths.horizon.tolist(), list(range(1, 8)))
        # 99 errors 0..98: rank ceil(100 * 0.9) = 90 -> value 89.
        self.assertTrue(widths.half_width.eq(89.0).all())

    def test_live_scores_replace_retrospective_errors_for_their_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "reports/uncertainty").mkdir(parents=True)
            residuals(days=40, error=5.0).assign(
                origin="2025-12-31", source="retrospective"
            ).to_csv(root / "reports/uncertainty/residuals.csv", index=False)
            pd.DataFrame(
                {
                    "Date": ["2026-01-02", "2026-03-01", "2026-01-02"],
                    "horizon": [1, 1, 1],
                    "model": ["ridge_1", "ridge_1", "other"],
                    "model_abs_error": [50.0, 60.0, 999.0],
                    "actual_first": [80.0, 90.0, 0.0],
                    "predicted_AQI": [30.0, 30.0, 999.0],
                }
            ).to_csv(root / "scores.csv", index=False)
            pool = load_residuals(root, "ridge_1", root)
        one = pool.loc[pool.horizon.eq(1)].set_index("Date").abs_error
        self.assertEqual(one[pd.Timestamp("2026-01-02")], 50.0)
        self.assertEqual(one[pd.Timestamp("2026-03-01")], 60.0)
        self.assertNotIn(999.0, one.to_numpy())
        self.assertFalse(pool.duplicated(["Date", "horizon"]).any())


class ExplanationTests(unittest.TestCase):
    def test_seasonal_terms_are_shuffled_as_one_input(self):
        grouped = groups(
            ["aqi_lag_0", "target_day_sin", "target_day_cos", "cams_pm25", "cams_aod"]
        )
        self.assertEqual(grouped["season"], ["target_day_sin", "target_day_cos"])
        self.assertEqual(grouped["cams"], ["cams_pm25", "cams_aod"])
        self.assertEqual(len(grouped), 3)

    def test_importance_flags_the_input_the_model_uses(self):
        frame = fixture()
        frame.index = pd.date_range("2024-09-01", periods=len(frame), name="Date")
        with (
            unittest.mock.patch("airquality.explain.FIT_END", "2024-12-15"),
            unittest.mock.patch("airquality.explain.TEST_END", "2025-12-31"),
        ):
            rows = pd.DataFrame(
                importance(
                    frame,
                    {"name": "r", "family": "ridge", "alpha": 1.0},
                    1,
                    repeats=5,
                )
            )
        self.assertEqual(rows.n.nunique(), 1)
        top = rows.sort_values("MAE_increase").feature.iloc[-1]
        self.assertTrue(top.startswith("aqi_"), top)


if __name__ == "__main__":
    unittest.main()
