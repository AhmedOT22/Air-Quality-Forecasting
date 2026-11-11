"""Train, compare and select the forecasting model, then score it on a held-out year.

Protocol (every step moves forward in time; nothing is tuned on the test year):

1. **Compare** every candidate on two validation years, 2024 and 2025. Each year is
   forecast by models fitted only on earlier data.
2. **Tune** the winning candidate's main setting on the same two years.
3. **Freeze** that configuration, then score it once on **2026**, alongside the
   naive baselines and the previous live model.

Candidates differ in the model type and in which inputs they see (see
``features.FEATURE_SETS``). Candidates that use CAMS air-quality forecasts are
scored for reference only: the CAMS archive holds near-term values at every lead,
so their back-test is an upper bound and they cannot be selected.

Run with ``python -m airquality train``. Results are written to ``reports/model``.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from airquality.aqi import category
from airquality.contract import validate
from airquality.features import build_features, seasonal_lag
from airquality.forecast_inputs import ForecastInputs

MODEL_VERSION = "2.0"  # bump deliberately when the model's behaviour changes
HORIZONS = range(1, 8)
VALIDATION_YEARS = (2024, 2025)
TEST_YEAR = 2026
BASELINES = ("persistence", "weekly")
CANDIDATES = [
    dict(name="persistence", family="persistence"),
    dict(name="weekly", family="weekly"),
    # The previous live model: AQI history, season and origin-day weather.
    dict(name="ridge_history", family="ridge", alpha=1.0, features="history"),
    dict(name="ridge_same_day", family="ridge", alpha=1.0, features="same_day"),
    dict(name="boosting_same_day", family="boosting", leaf=20, features="same_day"),
    dict(name="ridge_forecast", family="ridge", alpha=1.0, features="forecast"),
    dict(name="boosting_forecast", family="boosting", leaf=20, features="forecast"),
    dict(
        name="boosting_forecast_cams",
        family="boosting",
        leaf=20,
        features="forecast_cams",
        evidence="upper_bound",
    ),
]


def selectable(config):
    return config.get("evidence") != "upper_bound"


def estimator(config):
    if config["family"] == "boosting":
        # Shallow, slow-learning trees with an absolute-error loss (the metric is
        # MAE); missing inputs are handled natively.
        return HistGradientBoostingRegressor(
            loss="absolute_error",
            learning_rate=0.03,
            max_iter=300,
            max_leaf_nodes=7,
            min_samples_leaf=config["leaf"],
            l2_regularization=1.0,
            random_state=42,
        )
    return make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
        StandardScaler(),
        Ridge(alpha=config["alpha"]),
    )


def fit(frame, end, horizon, config, inputs=None):
    """Fit one horizon on rows whose target was observed by ``end``."""
    features, _, eligible, _ = build_features(
        frame, horizon, config.get("features", "history"), inputs, fit_end=end
    )
    y = frame.AQI.shift(-horizon)
    # AQI is final one day late, so a target day D is usable only if D+1 <= end.
    training = (
        eligible
        & y.notna()
        & (frame.index + pd.Timedelta(days=horizon + 1) <= pd.Timestamp(end))
    )
    if training.sum() < 30:
        raise ValueError("Insufficient chronological training rows")
    model = estimator(config).fit(features.loc[training], y.loc[training])
    fitted = np.maximum(0, model.predict(features.loc[training]))
    training_mae = float(np.abs(fitted - y.loc[training]).mean())
    return model, features, eligible, training_mae, int(training.sum())


def evaluate(frame, fit_end, evaluation_end, configs, horizons=HORIZONS, inputs=None):
    """Fit before ``fit_end`` and score after it; every model shares the same days."""
    frame = frame.loc[:evaluation_end]
    fit_end = pd.Timestamp(fit_end)
    records, diagnostics = [], []
    for h in horizons:
        target = frame.AQI.shift(-h)
        dates = frame.index + pd.Timedelta(days=h)
        fitted = {}
        mask = target.notna() & (frame.index >= fit_end) & (dates > fit_end)
        for config in configs:
            if config["family"] in BASELINES:
                _, _, eligible, _ = build_features(frame, h, "history")
            else:
                fitted[config["name"]] = fit(frame, fit_end, h, config, inputs)
                eligible = fitted[config["name"]][2]
            mask &= eligible
        origins = frame.index[mask]
        if origins.empty:
            raise ValueError("No eligible evaluation pairs")
        actual = target.loc[mask].to_numpy()
        persistence = frame.AQI.shift(1).loc[mask].to_numpy()
        for config in configs:
            family = config["family"]
            if family in BASELINES:
                lag = 1 if family == "persistence" else seasonal_lag(h, 1)
                predicted = frame.AQI.shift(lag).loc[mask].to_numpy()
                training_mae, count = np.nan, 0
            else:
                model, features, _, training_mae, count = fitted[config["name"]]
                predicted = np.maximum(0, model.predict(features.loc[mask]))
            error = predicted - actual
            diagnostics.append(
                {
                    "model": config["name"],
                    "horizon": h,
                    "n": len(actual),
                    "training_n": count,
                    "training_MAE": training_mae,
                    "MAE": float(np.abs(error).mean()),
                    "RMSE": float(np.sqrt(np.mean(error**2))),
                    "MAE_skill": float(
                        1 - np.abs(error).mean() / np.abs(persistence - actual).mean()
                    ),
                }
            )
            records.extend(
                {
                    "origin": origin,
                    "Date": origin + pd.Timedelta(days=h),
                    "horizon": h,
                    "model": config["name"],
                    "actual": a,
                    "predicted": p,
                }
                for origin, a, p in zip(origins, actual, predicted)
            )
    return pd.DataFrame(records), pd.DataFrame(diagnostics)


def tuning_grid(winner):
    family = winner["family"]
    rest = {k: v for k, v in winner.items() if k not in ("name", "alpha", "leaf")}
    stem = winner["name"].rsplit("_tuned", 1)[0]
    if family == "ridge":
        return [
            dict(rest, name=f"{stem}_alpha{alpha:g}", alpha=alpha)
            for alpha in (1.0, 10.0, 100.0)
        ]
    if family == "boosting":
        return [
            dict(rest, name=f"{stem}_leaf{leaf}", leaf=leaf) for leaf in (10, 20, 40)
        ]
    return [winner]  # baselines have nothing to tune


def choose(metrics, configs):
    """Lowest mean MAE with equal weight per year and horizon; ties keep list order."""
    allowed = [c["name"] for c in configs if selectable(c)]
    scores = metrics.loc[metrics.model.isin(allowed)].groupby("model").MAE.mean()
    name = min(allowed, key=lambda n: (scores[n], allowed.index(n)))
    return next(config for config in configs if config["name"] == name)


def validate_candidates(frame, configs, inputs, years=VALIDATION_YEARS):
    tables = []
    for year in years:
        _, metrics = evaluate(
            frame, f"{year - 1}-12-31", f"{year}-12-31", configs, inputs=inputs
        )
        tables.append(metrics.assign(fold=year))
    return pd.concat(tables, ignore_index=True)


def forward(frame, config, inputs=None):
    """Refit on everything available and forecast the seven days after the last day."""
    origin = frame.index[-1]
    rows = []
    for h in HORIZONS:
        if config["family"] in BASELINES:
            _, _, eligible, _ = build_features(frame, h, "history")
            if not eligible.iloc[-1]:
                raise ValueError("Latest completed origin lacks required AQI history")
            lag = 1 if config["family"] == "persistence" else seasonal_lag(h, 1)
            prediction = float(frame.AQI.iloc[-1 - lag])
        else:
            model, features, eligible, _, _ = fit(frame, origin, h, config, inputs)
            if not eligible.iloc[-1]:
                raise ValueError(
                    "Latest completed origin lacks required inputs; "
                    "do not issue a stale forecast"
                )
            prediction = max(0.0, float(model.predict(features.iloc[[-1]])[0]))
        rows.append(
            {
                "origin": origin,
                "Date": origin + pd.Timedelta(days=h),
                "horizon": h,
                "model": config["name"],
                "predicted_AQI": prediction,
                "predicted_category": category(int(np.floor(prediction + 0.5))),
            }
        )
    return pd.DataFrame(rows)


def reference_configs(selected):
    """Models reported beside the selected one on the test year."""
    names = {"persistence", "weekly", "ridge_history", "boosting_forecast_cams"}
    extra = [c for c in CANDIDATES if c["name"] in names]
    return [selected] + [c for c in extra if c["name"] != selected["name"]]


def run(output="reports/model"):
    frame, lock = validate()
    inputs = ForecastInputs.load()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    validation = validate_candidates(frame, CANDIDATES, inputs)
    validation.to_csv(output / "validation.csv", index=False)
    winner = choose(validation, CANDIDATES)
    grid = tuning_grid(winner)
    tuning = validate_candidates(frame, grid, inputs)
    tuning.to_csv(output / "tuning.csv", index=False)
    selected = choose(tuning, grid)
    test_end = f"{TEST_YEAR}-12-31"
    predictions, test = evaluate(
        frame,
        f"{TEST_YEAR - 1}-12-31",
        test_end,
        reference_configs(selected),
        inputs=inputs,
    )
    predictions.to_csv(output / "test_predictions.csv", index=False)
    test.to_csv(output / "test_metrics.csv", index=False)
    metadata = {
        "model_version": MODEL_VERSION,
        "dataset_lock": lock,
        "selected_config": selected,
        "candidate_winner": winner,
        "validation_years": list(VALIDATION_YEARS),
        "test_year": TEST_YEAR,
        "test_period": f"{predictions.Date.min().date()}/{predictions.Date.max().date()}",
        "selection_rule": "Lowest mean MAE with equal weight per validation year "
        "and horizon; CAMS candidates are reference only; the test year is excluded",
        "horizons": list(HORIZONS),
        "seed": 42,
        "caveats": [
            "Design-stage experiments looked at 2025 and 2026 scores for four "
            "configurations before this protocol was fixed; the rule itself "
            "selects on 2024-2025 only",
            "The weather-forecast archive starts in 2024; earlier training rows "
            "use observed weather as a stand-in, never rows that are scored",
            "CAMS back-tests are an upper bound: archived values are near-term "
            "forecasts at every lead",
            "2025 onward uses provisional Ontario observations",
            "Daily AQI is final one day late; no future measurement is used",
        ],
    }
    (output / "run.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return validation, tuning, test


if __name__ == "__main__":
    validation, tuning, test = run()
    print(validation.groupby("model").MAE.mean().sort_values().round(2).to_string())
    print(test.to_string(index=False))
