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
from etl_contract import validate
from workflow import fit

FIT_END, TEST_END = "2024-12-31", "2025-12-31"
REPEATS = 30
LABELS = {
    "aqi_lag_0": "AQI, latest available day",
    "aqi_lag_1": "AQI, 1 day earlier",
    "aqi_lag_2": "AQI, 2 days earlier",
    "aqi_lag_6": "AQI, 6 days earlier",
    "aqi_lag_13": "AQI, 13 days earlier",
    "aqi_mean_7d": "AQI, 7-day mean",
    "season": "Time of year (target date)",
    "temperature_c": "Temperature",
    "humidity_pct": "Relative humidity",
    "wind_speed_kmh": "Wind speed",
    "pressure_kpa": "Station pressure",
}


def groups(columns):
    result = {}
    for column in columns:
        key = "season" if column.startswith("target_day_") else column
        result.setdefault(key, []).append(column)
    return result


def importance(frame, config, horizon, repeats=REPEATS, seed=42):
    frame = frame.loc[:TEST_END]
    model, features, columns, eligible, _, _ = fit(frame, FIT_END, horizon, config)
    target = frame.AQI.shift(-horizon)
    dates = frame.index + pd.Timedelta(days=horizon)
    mask = (
        eligible
        & target.notna()
        & (frame.index >= pd.Timestamp(FIT_END))
        & (dates > pd.Timestamp(FIT_END))
    )
    x = features.loc[mask, columns].reset_index(drop=True)
    actual = target.loc[mask].to_numpy()

    def mae(data):
        return float(np.abs(np.maximum(0, model.predict(data)) - actual).mean())

    base = mae(x)
    rng = np.random.default_rng(seed + horizon)
    rows = []
    for key, members in groups(columns).items():
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
    config = json.loads(Path("reports/workflow/run.json").read_text())[
        "selected_config"
    ]
    table = pd.DataFrame(
        [row for h in range(1, 8) for row in importance(frame, config, h)]
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
                "evaluation": "2025-01-01/2025-12-31",
                "method": "Grouped permutation importance: mean MAE increase over "
                f"{REPEATS} shuffles per input group; seasonal sine/cosine shuffled jointly",
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
