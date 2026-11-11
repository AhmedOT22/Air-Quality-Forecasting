"""Turn forecasts into decisions: the chance of a poor-air day and how good alerts are.

A point forecast of "AQI 46" does not tell someone with asthma whether to move a
run indoors. This module converts each forecast into the probability that the day
ends above a threshold:

* **above 50** (Moderate or worse): unusually sensitive people may notice effects;
* **above 100** (Unhealthy for Sensitive Groups or worse).

The probability is the share of the model's recent errors (the same trailing
window the intervals use) that would push the forecast over the threshold. An
**alert** fires when that probability reaches a cut-off. The cut-off is chosen on
2025 and then scored, unchanged, on 2026.

Run with ``python -m airquality decisions``; results go to ``reports/decisions``.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from airquality.aqi import category
from airquality.uncertainty import MIN_RESIDUALS, WINDOW_DAYS, window_errors

THRESHOLDS = {"moderate": 50, "unhealthy_sensitive": 100}
CUTOFFS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7)
SELECTION_YEAR, EVALUATION_YEAR = 2025, 2026
MIN_RECALL = 0.7  # an alert that misses most poor-air days is not useful


def exceedance(prediction, errors, threshold):
    """P(actual > threshold) from recent signed errors (actual minus forecast)."""
    errors = np.asarray(errors, dtype=float)
    errors = errors[np.isfinite(errors)]
    if len(errors) < MIN_RESIDUALS:
        raise ValueError("At least 30 recent errors are required")
    # Add-one smoothing keeps probabilities off exactly 0 and 1.
    return float((np.sum(prediction + errors > threshold) + 0.5) / (len(errors) + 1))


def attach(forecast, residuals, origin, window=WINDOW_DAYS):
    """Add exceedance probabilities to a seven-day forecast table."""
    result = forecast.copy()
    for name, threshold in THRESHOLDS.items():
        result[f"p_{name}"] = [
            exceedance(
                row.predicted_AQI,
                window_errors(residuals, origin, row.horizon, window, "error"),
                threshold,
            )
            for row in result.itertuples()
        ]
    return result


def replay(stream, years, window=WINDOW_DAYS):
    """Probabilities each past forecast would have carried, using errors known then."""
    stream = stream.assign(
        Date=pd.to_datetime(stream.Date), origin=pd.to_datetime(stream.origin)
    )
    rows = stream.loc[stream.Date.dt.year.isin(years)].copy()
    for name, threshold in THRESHOLDS.items():
        values = []
        for row in rows.itertuples():
            errors = window_errors(stream, row.origin, row.horizon, window, "error")
            values.append(
                exceedance(row.predicted, errors, threshold)
                if len(errors) >= MIN_RESIDUALS
                else np.nan
            )
        rows[f"p_{name}"] = values
        rows[f"is_{name}"] = rows.actual > threshold
    return rows.dropna(subset=[f"p_{name}" for name in THRESHOLDS])


def alert_table(rows, event, cutoffs=CUTOFFS):
    """Hits, misses and false alarms of an alert at each probability cut-off."""
    records = []
    happened = rows[f"is_{event}"]
    for (year, horizon), group in rows.groupby([rows.Date.dt.year, "horizon"]):
        actual = happened.loc[group.index]
        for cutoff in cutoffs:
            alert = group[f"p_{event}"] >= cutoff
            hits = int((alert & actual).sum())
            records.append(
                {
                    "event": event,
                    "year": int(year),
                    "horizon": int(horizon),
                    "cutoff": cutoff,
                    "days": len(group),
                    "event_days": int(actual.sum()),
                    "alerts": int(alert.sum()),
                    "hits": hits,
                    "misses": int((~alert & actual).sum()),
                    "false_alarms": int((alert & ~actual).sum()),
                    "recall": hits / actual.sum() if actual.sum() else np.nan,
                    "precision": hits / alert.sum() if alert.sum() else np.nan,
                }
            )
    return pd.DataFrame(records)


def choose_cutoff(alerts, event, year=SELECTION_YEAR):
    """Highest-precision cut-off that still catches at least MIN_RECALL of event days.

    Pooled over horizons on the selection year. If no cut-off reaches the recall
    floor, the one with the highest recall is used.
    """
    pooled = (
        alerts.loc[alerts.event.eq(event) & alerts.year.eq(year)]
        .groupby("cutoff")[["hits", "misses", "false_alarms"]]
        .sum()
    )
    recall = pooled.hits / (pooled.hits + pooled.misses)
    precision = pooled.hits / (pooled.hits + pooled.false_alarms)
    passing = recall.index[recall >= MIN_RECALL]
    if len(passing):
        return float(precision.loc[passing].fillna(0).idxmax())
    return float(recall.idxmax())


def skill_table(rows, climatology):
    """Brier score (lower is better) against always quoting the usual frequency."""
    records = []
    for name in THRESHOLDS:
        for (year, horizon), group in rows.groupby([rows.Date.dt.year, "horizon"]):
            actual = group[f"is_{name}"].astype(float)
            brier = float(((group[f"p_{name}"] - actual) ** 2).mean())
            reference = float(((climatology[name] - actual) ** 2).mean())
            records.append(
                {
                    "event": name,
                    "year": int(year),
                    "horizon": int(horizon),
                    "days": len(group),
                    "event_days": int(actual.sum()),
                    "brier": brier,
                    "brier_climatology": reference,
                    "brier_skill": 1 - brier / reference if reference else np.nan,
                }
            )
    return pd.DataFrame(records)


def reliability(rows, event, year=EVALUATION_YEAR):
    """When the forecast said X%, how often did it happen?"""
    group = rows.loc[rows.Date.dt.year.eq(year)]
    bins = pd.cut(
        group[f"p_{event}"], [0, 0.1, 0.25, 0.5, 0.75, 1.0], include_lowest=True
    )
    table = group.groupby(bins, observed=True).agg(
        forecasts=(f"p_{event}", "size"),
        mean_probability=(f"p_{event}", "mean"),
        observed_frequency=(f"is_{event}", "mean"),
    )
    return table.reset_index(names="probability_bin").assign(
        event=event, probability_bin=lambda t: t.probability_bin.astype(str)
    )


def category_accuracy(predictions):
    """Share of days whose forecast lands in the observed AQI category."""
    right = predictions.predicted.round().astype(int).map(
        category
    ) == predictions.actual.round().astype(int).map(category)
    return right.groupby([predictions.model, predictions.horizon]).mean().unstack(0)


def run(output="reports/decisions"):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    stream = pd.read_csv("reports/uncertainty/residuals.csv")
    rows = replay(stream, (SELECTION_YEAR, EVALUATION_YEAR))
    before = stream.loc[pd.to_datetime(stream.Date).dt.year < SELECTION_YEAR]
    climatology = {
        name: float((before.actual > threshold).mean())
        for name, threshold in THRESHOLDS.items()
    }
    alerts = pd.concat([alert_table(rows, event) for event in THRESHOLDS])
    cutoffs = {event: choose_cutoff(alerts, event) for event in THRESHOLDS}
    alerts["chosen"] = alerts.cutoff.eq(alerts.event.map(cutoffs))
    alerts.to_csv(output / "alerts.csv", index=False)
    skill_table(rows, climatology).to_csv(output / "skill.csv", index=False)
    pd.concat([reliability(rows, event) for event in THRESHOLDS]).to_csv(
        output / "reliability.csv", index=False
    )
    rows.assign(
        origin=rows.origin.dt.strftime("%Y-%m-%d"),
        Date=rows.Date.dt.strftime("%Y-%m-%d"),
    ).drop(columns=["source", "abs_error"]).to_csv(
        output / "probabilities.csv", index=False, float_format="%.4f"
    )
    test = pd.read_csv("reports/model/test_predictions.csv")
    accuracy = category_accuracy(test)
    accuracy.to_csv(output / "category_accuracy.csv")
    chosen = alerts.loc[alerts.chosen & alerts.year.eq(EVALUATION_YEAR)]
    pooled = chosen.groupby("event")[
        ["event_days", "hits", "misses", "false_alarms"]
    ].sum()
    summary = {
        "thresholds": THRESHOLDS,
        "alert_cutoffs": cutoffs,
        "cutoff_rule": f"On {SELECTION_YEAR}, the highest-precision cut-off that "
        f"catches at least {MIN_RECALL:.0%} of event days, pooled over horizons",
        "evaluation_year": EVALUATION_YEAR,
        "pooled_alert_results": pooled.to_dict("index"),
        "climatology": climatology,
        "method": f"Share of signed errors in the trailing {WINDOW_DAYS} days that "
        "push the forecast above the threshold",
        "limitations": [
            "Days above 100 are rare, so their alert statistics rest on a handful "
            "of days and are indicative only",
            "Probabilities assume recent errors resemble the next one; sudden "
            "smoke events break that assumption",
        ],
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return alerts, summary


if __name__ == "__main__":
    alerts, summary = run()
    print(json.dumps(summary, indent=2))
