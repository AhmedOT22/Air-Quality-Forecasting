# Modelling

How the forecasting model is chosen, tested and turned into decisions. Everything
here is produced by one command and saved under `reports/`:

```bash
python -m airquality pipeline
```

## The task

Forecast the daily AQI at Toronto West 1 to 7 days after the last complete day of
data (the *origin day*). Each horizon has its own model. The benchmark is the naive
guess, "same as the latest known day".

## Inputs

Every input is known when the forecast is issued. They come in blocks
(`airquality/features.py`):

| Block | Inputs | First used by |
| --- | --- | --- |
| History | Final AQI 1, 2, 3, 7 and 14 days before the origin; its 7-day mean | all models |
| Calendar | Time of year of the target day | all models |
| Origin-day weather | Temperature, humidity, wind speed, pressure | all models |
| Same-day readings | Origin-day PM2.5 sub-score and peak, evening PM2.5, ozone and NO₂ peaks, afternoon ozone; previous-day sub-scores | `same_day` |
| Forecast weather | Temperature, humidity, wind speed and pressure forecast for the target day, as issued that many days earlier | `forecast` |
| CAMS | Modelled PM2.5, ozone and aerosol for the target day (horizons 1–5) | `forecast_cams` |

**Why the final AQI is a day late.** The ozone part of the AQI uses 8-hour windows
that run past midnight, so a day's AQI is final the next morning. The origin day's
PM2.5, by contrast, is already complete. The same-day block uses that.

**The stand-in rule.** The forecast-weather archive starts in 2024. For earlier
training days, observed weather stands in for the forecast so the model can learn
from all seven years. The stand-in is applied only to days inside the training
window; a day being scored or forecast always uses a real forecast. A test enforces
this.

## Selection protocol

1. **Compare** eight candidates on two validation years, 2024 and 2025. Each year is
   forecast by models fitted only on earlier data.
2. **Tune** the winner's main setting on the same years.
3. **Freeze** it and score it once on **2026**.

All models are scored on identical days. The rule is the lowest average error with
equal weight per year and horizon.

| Candidate | Inputs | Validation error |
| --- | --- | ---: |
| Naive: same as last week | | 15.6 |
| Naive: same as latest day | | 14.8 |
| Ridge (the previous live model) | history | 11.2 |
| Ridge | + same-day readings | 10.9 |
| Gradient boosting | + same-day readings | 10.7 |
| Ridge | + forecast weather | 9.7 |
| **Gradient boosting (selected)** | **+ forecast weather** | **9.3** |
| Gradient boosting (reference only) | + CAMS | 8.5 |

Gradient boosting is scikit-learn's `HistGradientBoostingRegressor` with an
absolute-error loss, shallow trees and a low learning rate. Tuning its minimum leaf
size (10, 20, 40) changed the error by less than 0.02 points; 10 was kept.

**Why CAMS cannot be selected.** Its archive holds near-term values at every lead,
so a back-test gives the model better information than a real 3-day smoke forecast
would. Its score is an upper bound. It runs live as a challenger, and the refresh
records real CAMS forecasts by lead so the question can be settled with evidence.

## Test results (2026)

January 1 to November 9, 244–249 days per horizon:

| Days ahead | Selected | Previous model | Naive | With CAMS (upper bound) |
| --- | ---: | ---: | ---: | ---: |
| 1 | 8.8 | 11.7 | 16.2 | 7.9 |
| 2 | 10.5 | 12.5 | 16.9 | 8.5 |
| 3 | 10.9 | 12.5 | 17.4 | 8.7 |
| 4 | 11.5 | 13.0 | 17.8 | 9.3 |
| 5 | 11.7 | 13.2 | 17.6 | 9.2 |
| 6 | 11.7 | 13.3 | 18.2 | 11.7 |
| 7 | 12.3 | 13.2 | 18.8 | 12.2 |
| **Mean** | **11.1** | **12.8** | **17.6** | **9.6** |

The selected model predicts the right AQI category on 76–84% of days (naive:
64–69%). Files: `reports/model/`.

## Likely range

Each forecast gets a 90% range (`airquality/uncertainty.py`). The half-width is the
conformal 90th-percentile absolute error over the **previous 180 days**, per horizon,
using only errors known at the origin. The window was chosen on 2025 from 90, 180
and 365 days by a rule fixed in advance; on 2026 it covered 90–92% at every horizon.
In production the window mixes back-test errors with scored live forecasts, which
gradually take over.

## From forecast to decision

`airquality/decisions.py` converts each forecast into the chance of exceeding
AQI 50 and AQI 100: the share of the last 180 days' signed errors that would push the
forecast over the threshold. A day is **flagged** when that chance reaches a cut-off.
The cut-off is the highest-precision one that still caught at least 70% of event days
in 2025, then it is scored unchanged on 2026:

| Event | Cut-off | Caught | Flags that were right |
| --- | ---: | ---: | ---: |
| Above 50, one day ahead | 20% | 86% | 51% |
| Above 50, all horizons | 20% | 82% | 37% |
| Above 100, one day ahead | 10% | 3 of 4 days | 3 of 3 |
| Above 100, two or more days ahead | 10% | 0 of 4 days | no flags raised |

The chances are roughly calibrated: forecasts of 25–50% came true 35% of the time,
and forecasts above 75% came true 81% of the time. Files: `reports/decisions/`.

## What the model relies on

`airquality/explain.py` shuffles each input group on the test year and measures the
rise in error. One day ahead, the origin day's PM2.5 dominates (about 4 points). From
two days out, forecast temperature (about 2 points), origin-day weather, forecast
wind and the season carry the forecast; the older AQI history adds almost nothing.
Importance shows what the model leans on, not what causes pollution.

## Caveats

- **Design-stage peeking.** Before this protocol was fixed, exploratory runs looked
  at 2025 and 2026 scores for four configurations. Both years told the same story
  and the rule selects on 2024–2025 only, but 2026 is not a perfectly blind test.
- **Smoke.** The model pulls forecasts toward typical values: about 8 points high on
  the cleanest days and far too low on smoke days. Four test days exceeded 100.
- **Dependence.** Daily errors are correlated, so small differences between models
  (such as boosting against Ridge on the same inputs) are not established.
- **Provisional data.** Readings from 2025 onward can be revised.
- **Chances come from recent errors.** After a quiet spell they understate smoke
  risk; after a smoke episode they overstate it for a while.

## Changing the model

`MODEL_VERSION` in `airquality/training.py` and the selected configuration together
identify the live model. Bump the version when behaviour changes; the live track
record then starts a new series. To promote a challenger, require a clear win on the
live record (at least 90 scored forecasts per horizon), not on a back-test.
