# Automatic forecasts and prospective monitoring

The GitHub Actions workflow `Refresh forecasts and monitor outcomes` runs at **11:17
and 17:17 UTC daily** and supports manual dispatch. In Toronto that is 07:17/13:17
in daylight time and 06:17/12:17 in standard time. The second attempt allows recovery
from morning provider delays. GitHub scheduling is best effort, not an uptime SLA.

Run locally with `python operations.py`. The default downloads fresh pollution and
weather; `--snapshot` is a freshness-checked smoke option, not a bypass for old data.
No API keys are needed for the currently configured public sources.

## Refresh and publication

1. Verify the locked historical release. Keep its ETL and selected Ridge alpha 1 fixed.
2. Refresh observations into temporary staging, preserving the frozen notebook data.
3. Apply the same ETL validation contract to the candidate production snapshot.
4. Require exactly yesterday's completed EST origin, pollution no older than six
   hours, all four origin-day weather fields and the required observed AQI lag history.
5. Refit the approved model and generate seven daily predictions. Missing/stale
   inputs block issuance; no quiet fallback to an earlier origin occurs.
6. Archive the first issuance per origin/model version. Reruns cannot rewrite it.
7. Commit small reports/history to the `data` branch (keeping automated commits out
   of `main`) and retain full input snapshots as workflow artifacts for 90 days. Raw download caching reduces repeated national downloads.

`status.json` is authoritative for freshness and success. A failed refresh records
`publication_status: blocked`, preserves the prior forecast as historical output,
and fails the workflow visibly. The schedule does not retune models or automatically
promote a challenger. Publication is restricted to `reports/operational/`; frozen
benchmark snapshots and their lock are not renewed by the scheduled job.

The release snapshot remains manually locked. Automatic refreshes are validated
candidate production versions under that fixed contract, not implicit changes to
cleaning rules or a replacement of the reproducible historical analysis.

## Forecast and observation ledger

`forecast_history.csv` stores issuance time, target date, origin, horizon, model
identity, implementation revision, prediction, optional bounds, input checksum and
both baseline predictions. Model identity includes hyperparameters and relevant
forecast implementation bytes. New versions remain distinguishable in metrics.
Issuance time is read after inference. Scoring accepts ISO timestamps with or
without fractional seconds; monitoring alerts include the model version.

Only target dates that start after the issuance's fixed-EST date count as
**prospective**. Same-day h1 forecasts are retained and explicitly excluded from
prospective performance; the current completed-day design therefore initially
collects strictly prospective evidence for horizons 2–7.

AQI for date D may include next-morning ozone. Observations are scored only after
completed D+1, conservatively from D+2 at 00:00 EST. Only dates for already issued
forecasts are collected. There is no manufactured historical prospective track record.

`observation_history.csv` preserves the first eligible observed truth and later
value/quality revisions, including reversions to an earlier value. `scores.csv`
uses first eligible truth for headline errors and retains latest truth separately.
Provider truth remains provisional and can be revised. Missing targets stay unscored.

`metrics.csv` reports MAE/RMSE, persistence and weekly MAE, persistence skill and
interval coverage by model version/horizon on identical eligible pairs.
`rolling_metrics.csv` uses the latest 30 scored target days per version/horizon.
`alerts.json` flags worse-than-persistence MAE after at least 20 pairs, or a 50%
increase versus the preceding 30-pair window (also at least 20). These are local
report diagnostics, not external notifications or significance tests. Overlapping
forecast windows are dependent. With no mature observations, metrics remain empty
and alerts explicitly say `collecting_observations`.

## Prediction intervals

`uncertainty.py` builds rolling split-conformal intervals. Each horizon's half-width
is the finite-sample 90% quantile of absolute out-of-sample errors whose target dates
fall in the 180 days before the forecast origin; lower AQI is bounded at zero.

The error stream comes from yearly chronological refits: 2023 is forecast by a model
fitted through 2022, and so on to October 2026 (`reports/uncertainty/residuals.csv`).
At each refresh `operations.py` adds the scored live errors of the primary model,
which replace retrospective errors on the same date and horizon, and recomputes the
widths. If a window holds fewer than 30 errors, the latest 180 known errors are used.

The window was chosen on 2025 only, from 90/180/365/730 days, by a rule fixed in
advance: every horizon within one point of 90%, then the narrowest band. The 180-day
window covered 90.0–90.6% per horizon in 2025. **On held-out 2026 it covered
89.8–90.8% per horizon** (`calibration.csv`, `window_selection.csv`). The previous
fixed calibration (January–June 2026) covered only 79–87% over July–September,
because it never saw summer errors.

Serial dependence and nonstationarity mean coverage is an estimate, not a guarantee.
Live first-issuance coverage is measured separately. Do not interpret the bands as
validated health-warning intervals.

## Forecast-weather integration

`forecast_weather.py` retrieves Open-Meteo lead-specific archived forecasts from
2024 onward and current hourly forecasts for Pearson, normalizing fixed EST,
18-hour coverage, temperature, humidity, wind speed and pressure (hPa → kPa).
These are model forecasts, not observed target-day weather.

`weather_model.py` adds the archived horizon-specific forecast variables to the
same AQI-history features and fits a Ridge alpha 1 challenger. Its 2026 Jan–Sep
retrospective comparison uses identical pairs to the approved Ridge and persistence,
with fitting ending in 2025. One-day MAE was 10.962 versus 11.816 for the approved
Ridge on 209 common pairs. This is exploratory, not a promotion decision.

Fixed-lead archived fields are proxies for forecasts from the origin day; exact
provider publication timestamps are not available. Therefore the historical
comparison is not claimed to be exact production-vintage validation. The live
weather payload, source checksum and retrieval time are preserved before challenger
issuance. The current forecast is fetched before the recorded issuance time.

Both primary and experimental challenger predictions are archived and monitored
separately. Challenger weather failure leaves a valid primary forecast available
and writes `weather_status.json` with the reason. The challenger has no interval
bounds yet; primary calibration is not reused for a different model.

Weather data: [Open-Meteo](https://open-meteo.com/), CC BY 4.0.
[Previous Runs documentation](https://open-meteo.com/en/docs/previous-runs-api).
No provider concentration/AQHI forecasts are substituted for this project's AQI model.

## Outputs

The live ledger lives on the [`data` branch](https://github.com/AhmedOT22/Air-Quality-Forecasting/tree/data/reports/operational);
`reports/operational/` on `main` is a snapshot used for offline dashboard tests and the notebook.

- `latest_forecast.csv`: latest primary and challenger predictions.
- `forecast_history.csv`, `observation_history.csv`: persistent prediction/truth history.
- `scores.csv`, `metrics.csv`, `rolling_metrics.csv`, `alerts.json`: prospective diagnostics.
- `status.json`, `latest_manifest.json`, `weather_status.json`: freshness and provenance.
- Workflow artifacts: production daily/hourly snapshots and lock, weather forecast
  payloads/sidecars and interval calibration. Artifacts expire after 90 days; the
  committed ledgers persist. This is not a claim of indefinite raw snapshot retention.

A Streamlit interface is available in `app.py`; see [dashboard setup](dashboard.md).
It reads these reports and never triggers training or data refresh from the UI.
Prospective performance requires future observations to arrive, so successful
deployment does not itself demonstrate forecast skill.
