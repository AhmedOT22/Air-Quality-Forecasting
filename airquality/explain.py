"""What drives the selected model: grouped permutation importance on the 2025 hold-out.

For each horizon the selected configuration is fitted through 2024 (as in the final
evaluation) and scored on 2025. Each input group is then shuffled across 2025 rows,
and the increase in MAE measures how much the forecast relies on that input. The
two seasonal terms are shuffled together so time of year counts as one input.
"""

import json
from pathlib import Path
import numpy as np
import pandas as pd
from airquality.contract import validate
from airquality.forecast_inputs import ForecastInputs
from airquality.training import fit

FIT_END, TEST_END = "2025-12-31", "2026-12-31"
REPEATS = 30
LABELS = {
    "aqi_lag_0": "AQI, latest final day",
    "aqi_lag_1": "AQI, 1 day earlier",
    "aqi_lag_2": "AQI, 2 days earlier",
    "aqi_lag_6": "AQI, 6 days earlier",
    "aqi_lag_13": "AQI, 13 days earlier",
    "aqi_mean_7d": "AQI, 7-day mean",
    "season": "Time of year",
    "weather_today": "Weather on the origin day",
    "pm25_today": "PM2.5 on the origin day",
    "ozone_today": "Ozone on the origin day",
    "no2_today": "NO2 on the origin day",
    "pollutants_previous": "Pollutant sub-indices, previous day",
    "forecast_temperature_c": "Forecast temperature",
    "forecast_humidity_pct": "Forecast humidity",
    "forecast_wind_speed_kmh": "Forecast wind speed",
    "forecast_pressure_kpa": "Forecast pressure",
    "cams": "CAMS air-quality forecast",
}
GROUPS = {
    "season": ("target_day_sin", "target_day_cos"),
    "weather_today": (
        "temperature_c",
        "humidity_pct",
        "wind_speed_kmh",
        "pressure_kpa",
    ),
    "pm25_today": ("PM25_AQI_origin", "PM25_max_1h_origin", "PM25_evening_origin"),
    "ozone_today": ("O3_max_1h_origin", "O3_afternoon_origin"),
    "no2_today": ("NO2_max_1h_origin",),
    "pollutants_previous": (
        "PM25_AQI_previous",
        "O3_AQI_previous",
        "NO2_AQI_previous",
    ),
}
MEMBER = {column: key for key, columns in GROUPS.items() for column in columns}


def groups(columns):
    """Inputs that measure the same thing are shuffled together as one group."""
    result = {}
    for column in columns:
        key = MEMBER.get(column, "cams" if column.startswith("cams_") else column)
        result.setdefault(key, []).append(column)
    return result


def importance(frame, config, horizon, inputs=None, repeats=REPEATS, seed=42):
    frame = frame.loc[:TEST_END]
    model, features, eligible, _, _ = fit(frame, FIT_END, horizon, config, inputs)
    target = frame.AQI.shift(-horizon)
    dates = frame.index + pd.Timedelta(days=horizon)
    mask = (
        eligible
        & target.notna()
        & (frame.index >= pd.Timestamp(FIT_END))
        & (dates > pd.Timestamp(FIT_END))
    )
    x = features.loc[mask].reset_index(drop=True)
    actual = target.loc[mask].to_numpy()

    def mae(data):
        return float(np.abs(np.maximum(0, model.predict(data)) - actual).mean())

    base = mae(x)
    rng = np.random.default_rng(seed + horizon)
    rows = []
    for key, members in groups(x.columns).items():
        increases = []
        for _ in range(repeats):
            shuffled = x.copy()
            order = rng.permutation(len(x))
            shuffled[members] = x[members].to_numpy()[order]
            increases.append(mae(shuffled) - base)
        rows.append(
            {
                "horizon": horizon,
                "feature": key,
                "label": LABELS.get(key, key),
                "MAE_increase": float(np.mean(increases)),
                "MAE_increase_sd": float(np.std(increases, ddof=1)),
                "baseline_MAE": base,
                "n": len(x),
            }
        )
    return rows


def run(output="reports/explain"):
    frame, lock = validate()
    config = json.loads(Path("reports/model/run.json").read_text())["selected_config"]
    inputs = ForecastInputs.load()
    table = pd.DataFrame(
        [row for h in range(1, 8) for row in importance(frame, config, h, inputs)]
    )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    table.to_csv(output / "importance.csv", index=False)
    (output / "run.json").write_text(
        json.dumps(
            {
                "dataset_lock": lock,
                "config": config,
                "fit_end": FIT_END,
                "evaluation": f"{FIT_END[:4]}-12-31 onward (the test year)",
                "method": "Grouped permutation importance: mean MAE increase over "
                f"{REPEATS} shuffles per input group; related inputs shuffled jointly",
                "limitations": [
                    "Correlated inputs share credit: shuffling one AQI lag leaves the others, so each lag alone looks less important than AQI history as a whole",
                    "Importance describes reliance of this fitted model on 2025 data, not causal effects on air quality",
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return table


if __name__ == "__main__":
    result = run()
    print(
        result.pivot(index="label", columns="horizon", values="MAE_increase")
        .round(2)
        .to_string()
    )
