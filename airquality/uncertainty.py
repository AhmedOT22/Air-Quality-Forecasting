"""Rolling split-conformal prediction intervals by horizon.

Each interval half-width is the finite-sample conformal quantile of absolute
out-of-sample errors whose target dates fall in the trailing WINDOW_DAYS before the
forecast origin. Errors come from yearly chronological refits (each year forecast by
a model fitted only on earlier years) and, operationally, from scored live forecasts.
A trailing window lets the width follow seasonal and year-to-year changes in error,
which a single fixed calibration period missed.

Window selection used 2025 only; 2026 is the held-out check.
"""

import json
from pathlib import Path
import numpy as np
import pandas as pd
from airquality.contract import validate
from airquality.forecast_inputs import ForecastInputs
from airquality.training import evaluate

COVERAGE = 0.90
WINDOW_DAYS = 180
MIN_RESIDUALS = 30
CANDIDATE_WINDOWS = (90, 180, 365)
STREAM_YEARS = (2024, 2025, 2026)  # the forecast-by-lead archive starts in 2024
SELECTION_YEAR, EVALUATION_YEAR = 2025, 2026


def residual_width(errors, coverage=COVERAGE):
    errors = np.asarray(errors, dtype=float)
    errors = errors[np.isfinite(errors)]
    if len(errors) < MIN_RESIDUALS:
        raise ValueError("At least 30 calibration residuals required per horizon")
    rank = min(len(errors), int(np.ceil((len(errors) + 1) * coverage)))
    return float(np.sort(np.abs(errors))[rank - 1])


def residual_stream(frame, config, inputs=None, years=STREAM_YEARS):
    """Out-of-sample errors; each year uses a model fitted before it began."""
    parts = []
    for year in years:
        predictions, _ = evaluate(
            frame, f"{year - 1}-12-31", f"{year}-12-31", [config], inputs=inputs
        )
        parts.append(predictions)
    stream = pd.concat(parts, ignore_index=True)
    stream["error"] = stream.actual - stream.predicted
    stream["abs_error"] = stream.error.abs()
    stream["source"] = "retrospective"
    return stream[
        [
            "origin",
            "Date",
            "horizon",
            "predicted",
            "actual",
            "error",
            "abs_error",
            "source",
        ]
    ]


def window_errors(residuals, origin, horizon, window=WINDOW_DAYS, column="abs_error"):
    """Errors known at the origin (target date before it) in the trailing window.

    Falls back to the most recent `window` known errors when the calendar window
    holds fewer than MIN_RESIDUALS, for example after a long data gap.
    """
    origin = pd.Timestamp(origin)
    known = residuals.loc[
        residuals.horizon.eq(horizon) & (residuals.Date < origin)
    ].sort_values("Date")
    recent = known.loc[known.Date >= origin - pd.Timedelta(days=window)]
    if len(recent) < MIN_RESIDUALS:
        recent = known.tail(window)
    return recent[column].to_numpy()


def trailing_widths(residuals, origin, window=WINDOW_DAYS, coverage=COVERAGE):
    rows = []
    for h in range(1, 8):
        errors = window_errors(residuals, origin, h, window)
        rows.append(
            {
                "horizon": h,
                "half_width": residual_width(errors, coverage),
                "nominal_coverage": coverage,
                "calibration_n": len(errors),
            }
        )
    return pd.DataFrame(rows)


def backtest(stream, window, years):
    """Replay the rule day by day: each forecast gets the width known at its origin."""
    stream = stream.assign(Date=pd.to_datetime(stream.Date))
    rows = []
    for (h, year), group in stream.assign(year=stream.Date.dt.year).groupby(
        ["horizon", "year"]
    ):
        if year not in years:
            continue
        covered, widths = [], []
        for origin, error in zip(group.origin, group.abs_error):
            width = residual_width(window_errors(stream, origin, h, window))
            covered.append(error <= width)
            widths.append(2 * width)
        rows.append(
            {
                "window_days": window,
                "year": int(year),
                "horizon": int(h),
                "n": len(group),
                "observed_coverage": float(np.mean(covered)),
                "mean_interval_width": float(np.mean(widths)),
            }
        )
    return pd.DataFrame(rows)


def calibrate(output="reports/uncertainty"):
    frame, lock = validate()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads(Path("reports/model/run.json").read_text())["selected_config"]
    stream = residual_stream(frame, config, ForecastInputs.load())
    stream.assign(
        origin=stream.origin.dt.strftime("%Y-%m-%d"),
        Date=stream.Date.dt.strftime("%Y-%m-%d"),
    ).to_csv(output / "residuals.csv", index=False)
    selection = pd.concat(
        [
            backtest(stream, window, (SELECTION_YEAR, EVALUATION_YEAR))
            for window in CANDIDATE_WINDOWS
        ],
        ignore_index=True,
    )
    selection.to_csv(output / "window_selection.csv", index=False)
    # Pre-stated rule on 2025 only: every horizon at or above nominal minus 1 point,
    # then the narrowest mean width; otherwise the highest minimum coverage.
    chosen = selection.loc[selection.year.eq(SELECTION_YEAR)].groupby("window_days")
    summary = chosen.agg(
        minimum=("observed_coverage", "min"), width=("mean_interval_width", "mean")
    )
    passing = summary.loc[summary.minimum >= COVERAGE - 0.01]
    window = int(
        passing.width.idxmin() if not passing.empty else summary.minimum.idxmax()
    )
    if window != WINDOW_DAYS:
        raise ValueError(
            f"Selection chose a {window}-day window; update WINDOW_DAYS deliberately"
        )
    table = selection.loc[
        selection.window_days.eq(window) & selection.year.eq(EVALUATION_YEAR)
    ].drop(columns=["window_days", "year"])
    latest = trailing_widths(stream, frame.index[-1])
    table = latest.merge(
        table.rename(columns={"n": "evaluation_n"}), on="horizon", validate="one_to_one"
    )
    table.to_csv(output / "calibration.csv", index=False)
    (output / "run.json").write_text(
        json.dumps(
            {
                "dataset_lock": lock,
                "config": config,
                "method": "Rolling split conformal: finite-sample 90% quantile of absolute "
                f"out-of-sample errors in the trailing {window} days, per horizon; lower bound at zero",
                "residual_stream": "Yearly chronological refits 2024-2026 (fit through the prior year)",
                "window_selection": f"{SELECTION_YEAR} only; candidates {list(CANDIDATE_WINDOWS)} days",
                "held_out_evaluation": f"{EVALUATION_YEAR}-01-01/{frame.index[-1].date()}",
                "operational": "Each refresh recomputes widths from the trailing window, "
                "adding scored live forecasts to the retrospective stream",
                "limitations": [
                    "Serial dependence and nonstationarity rule out a guaranteed coverage; the window adapts, it does not certify",
                    "Retrospective errors come from yearly refits, while the live model is refit each run",
                    "Live interval coverage is reported separately once forecasts are scored",
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return table


def load_residuals(reports_dir, model, root=Path(__file__).resolve().parents[1]):
    """Retrospective stream plus scored live errors for `model`; live wins on overlap."""
    retrospective = pd.read_csv(root / "reports/uncertainty/residuals.csv")
    frames = [retrospective[["Date", "horizon", "error", "abs_error"]]]
    scores_path = Path(reports_dir) / "scores.csv"
    if scores_path.exists():
        scores = pd.read_csv(scores_path)
        if not scores.empty:
            mine = scores.loc[scores.model.eq(model)]
            live = mine[["Date", "horizon"]].assign(
                error=mine.actual_first - mine.predicted_AQI,
                abs_error=mine.model_abs_error,
            )
            frames.insert(0, live)
    residuals = pd.concat(frames, ignore_index=True)
    residuals["Date"] = pd.to_datetime(residuals.Date)
    return residuals.drop_duplicates(["Date", "horizon"], keep="first")


def attach(forecast, table):
    result = forecast.merge(
        table[["horizon", "half_width", "nominal_coverage"]],
        on="horizon",
        validate="one_to_one",
    )
    if len(result) != len(forecast):
        raise ValueError("Missing interval calibration horizon")
    result["lower_AQI"] = (result.predicted_AQI - result.half_width).clip(lower=0)
    result["upper_AQI"] = result.predicted_AQI + result.half_width
    return result


if __name__ == "__main__":
    print(calibrate().to_string(index=False))
