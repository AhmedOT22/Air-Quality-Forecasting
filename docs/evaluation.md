# AQI benchmark

The PM2.5 concentration results remain supplementary under `reports/2023/`
and `reports/2024/`. The main benchmark now uses `daily_aqi.csv` and writes
`reports/aqi/2023/` and `reports/aqi/2024/`. Its errors are **AQI points**, not µg/m³.

The index retains the original four-pollutant scope, with an explicit fixed
EPA-2024-based definition and a separate EPA-2018 comparison column. It is not a
full official Toronto AQI or Canada's AQHI.

## Availability correction

Ozone windows for day D can extend into D+1 at 07:00. Therefore, after completed
origin day t, the latest index allowed into features is **AQI(t−1)**. The lag feature
set relative to origin t is 1, 2, 3, 7 and 14 days, plus the seven-day mean ending
t−1. Calendar features still describe the future target date. Completed day t
weather is available, but no future observed weather is used.

Training also respects this delay: an AQI label for day D is eligible for fitting
only if D+1 is at/before the fitting boundary. Otherwise the training target could
already contain post-boundary ozone observations. Tests mutate the unavailable
current-origin index as well as future labels to verify first-trajectory invariance.

Persistence repeats the latest available AQI(t−1). Weekly naïve repeats the latest
available seven-day pattern. At horizon seven, AQI(target−7) would be AQI(t), which
is still unavailable, so the baseline uses the preceding available week instead.
All models share exactly the same eligible origin/target pairs within each horizon.

The 2023 exercise has 247 one-day and 232 seven-day pairs; 2024 has 308 and 302.
This reduction relative to PM2.5 is expected: all four pollutant components and the
required lag history must be available. Missing SO2 is a substantial 2023 limitation.
Scores are conditional on this observed subset.

## Interpreting the results correctly

With EPA 2024 targets, one-day forest+weather MAE in 2024 is 9.119 AQI points
against persistence 12.656, a 27.9% reduction. In 2023, one-day Ridge
MAE is 13.984 against persistence 17.283, a 19.1% reduction.
These describe performance against same-source baselines only. Earlier EPA 2018
scores use a different target scale and are not a controlled model-improvement
comparison. The standard migration does not establish that overfitting is resolved.


The old data source's raw files are unavailable. The original saved scores used a
different index construction, imputation and evaluation protocol. Neither the new
AQI metrics nor the earlier PM2.5 metrics establish that replacing the source alone
improved forecast accuracy. A source-only experiment requires common observed dates,
the same fixed AQI definition, and identical fitting/availability rules on both inputs.


---

# Supplementary PM2.5 analysis (not the main AQI target)

# Evaluation and interpretation

## Task

Predict daily mean PM2.5 concentration (µg/m³) at Toronto West at lead times 1–7 days.
An origin is the **completed local-standard day**. The retrospective benchmark assumes
that day's finalized pollution and weather observations are available. It does not
simulate publication delays or vintage revisions and is not a live warning system.

## Chronological exercises

| Evaluation period | Fitting targets end | Input start | Holdout length |
| --- | --- | --- | --- |
| 2023 | 2022-12-31 | 2020-01-01 | 365 days |
| 2024 | 2023-12-31 | 2020-01-01 | 366 days |

Each horizon has separate direct estimators. A training origin is used only when
its target date is at or before the fitting boundary. Later evaluation observations
can update the available feature history, but models and imputers remain fixed
throughout that year's evaluation.

The 2024 exercise includes 2023 observations in its training window. The two
exercises are not independent tests, and neither is a permanently untouched lockbox
for future model development. Model settings below were fixed before this comparison;
no holdout tuning or claimed optimal parameters are involved.

## Features and models

All pollution features refer to the origin or earlier: lags 0, 1, 2, 6 and 13 calendar
days, plus the seven-day trailing mean requiring all seven observations. Calendar
sine/cosine terms describe the known target day of year. Weather features are daily
means at the completed origin: temperature, relative humidity, wind speed and pressure.
No observed target-day or intermediate future weather is used.

- **Ridge + weather:** median imputation, missing indicators, standardization, alpha 10.
- **Forest, pollution only:** 200 trees, minimum leaf size 5, seed 42.
- **Forest + weather:** identical forest settings with weather added.
- **Persistence:** repeat the origin's observed concentration for every horizon.
- **Weekly seasonal naïve:** use the observed concentration on target date minus seven days.

Weather imputation statistics and scaling are fit on training rows only. Pollution
features must already be observed; no target or pollution lag is imputed. Predictions
are bounded below at zero. No upper bound clips real pollution episodes.

Direct models avoid recursively assuming future measured weather is known. This
supersedes the earlier standalone recursive lag-only AQI workflow.

## Fair pairs, gaps, and metrics

All models are evaluated on exactly the same eligible origin/target pairs **within
each horizon**. Origins start on the last fitting day. Targets must be observed,
and the pollution history needed by the features/baselines must exist. The calendar
is never compressed after dropping missing values.

| Year | 1-day eligible pairs | 7-day eligible pairs |
| --- | ---: | ---: |
| 2023 | 335 | 326 |
| 2024 | 355 | 348 |

Pair counts vary by horizon because later targets can lie beyond the holdout or
be missing. Metrics are conditional on these observed pairs, not on every date.
Gaps may be non-random; report this limitation rather than assuming exclusion is harmless.
Overlapping origins are dependent, so counts are not independent sample sizes.

Reports include MAE, RMSE and `1 - model_MAE / persistence_MAE`; positive skill means
lower MAE than persistence. Monthly one-day errors help reveal temporal variation.
No confidence intervals, statistical significance or causal attribution are claimed.

## Findings

Ridge improves one-day MAE over persistence by 14.3% in 2023 and 15.6% in 2024.
The weather-assisted forest improves on its pollution-only counterpart at one day
in both years, but not at seven days by MAE. At seven days, pollution-only forest
MAE is 4.825 in 2023 and 3.185 in 2024, compared with persistence 7.008 and 4.353.
Other metrics and horizons can favour another model; inspect the full tables.

2023 errors are larger. Source method changes, sparse extreme events, omitted
spatial/smoke predictors, and the airport weather proxy limit generalization.
This benchmark does not identify which factor explains any individual error.

After holdout scoring, estimators are separately refit using all observations up
to the archive endpoint to produce `forecast.csv`. Those projections do not alter
holdout metrics and are not current forecasts. If the endpoint lacks eligible
pollution history, an empty forecast and explicit status are written.

## Archived exploration

`notebooks/legacy/AirQuality.ipynb` and `calculation.py` preserve the original work,
not the current modelling path. Its derived AQI construction, full-series imputation,
random splits, same-day pollutant predictors, in-sample comparisons and old saved
accuracy claims remain unsuitable as unbiased future-forecast evidence. Its results
are not comparable with the new PM2.5 target and are not reused in the main notebook.
