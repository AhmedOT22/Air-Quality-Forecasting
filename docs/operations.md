# Operations

How the outlook is produced, recorded and scored every day, and how to run the
dashboard.

## The scheduled refresh

`.github/workflows/refresh.yml` runs at 11:17 and 17:17 UTC, and on pushes that
change the model or data. It runs `python -m airquality refresh`, which:

1. **Downloads fresh observations** into a temporary folder. The locked research
   dataset is never modified.
2. **Validates** them with the same data contract as the research dataset.
3. **Checks freshness:** the last complete day must be yesterday, pollution readings
   under six hours old, weather complete, and the required AQI history present.
4. **Fetches forecast inputs:** the weather forecast for the next seven days
   (required) and the CAMS forecast (for the challenger only).
5. **Refits** the frozen model configuration on all available history and issues
   seven forecasts, each with a likely range and the chances of exceeding AQI 50
   and 100.
6. **Records** them in the forecast ledger. A forecast for a given day, horizon and
   model version is written once and never changed.
7. **Scores** earlier forecasts whose real AQI has since arrived.
8. **Publishes** the ledger to the `data` branch, keeping automated commits off
   `main`.

The refresh never retunes or reselects the model.

## When no forecast is issued

| Situation | What happens |
| --- | --- |
| Inputs not ready (for example, yesterday's weather not yet published) | The run records `publication_status: blocked` with the reason and finishes **green**, with a "No forecast issued" notice. The next run tries again. |
| A download fails, data is invalid, or the code errors | The run **fails** (red) and records the error. |
| The CAMS forecast is unavailable | The main outlook is still issued; only the challenger is skipped. |

The dashboard shows a blocked refresh as a warning and keeps the last outlook, marked
as historical.

## The ledger (`reports/operational/`)

| File | Contents |
| --- | --- |
| `status.json` | Result of the latest run and why |
| `latest_forecast.csv` | The current 7-day outlook |
| `forecast_history.csv` | Every forecast ever issued, with its model version |
| `observation_history.csv` | The observed AQI for forecast days, as first seen and as revised |
| `scores.csv`, `metrics.csv`, `rolling_metrics.csv` | Each scored forecast; error by model and horizon |
| `forecast_inputs.csv` | The weather and CAMS forecasts retrieved at each run, by lead: the honest record for judging the challenger later |
| `alerts.json` | Monitoring notes, such as a model doing worse than the naive guess |

Rules for an honest live record:

- The first-day forecast is issued the same morning, so only days 2–7 count as
  genuinely ahead of time.
- A forecast is scored against the AQI as first published; later revisions are kept
  alongside.
- Each forecast carries a model version, a hash of the model configuration and
  `MODEL_VERSION`. Editing code does not change it; changing the model does.
- Live accuracy is shown only once a horizon has 30 scored forecasts.

The copy of this folder on `main` is a bundled sample for the notebook, tests and
offline use. The live ledger is on the `data` branch.

## Run a refresh by hand

```bash
python -m airquality refresh
```

It needs network access and writes to `reports/operational/`. To exercise the code on
the locked dataset without downloading observations:

```bash
python -m airquality refresh --snapshot
```

## The dashboard

```bash
streamlit run app.py
```

It is read-only: it displays published reports and never trains a model or calls the
pollution sources. It reads the ledger from the `data` branch, falls back to `main`,
then to the bundled copy, and says which one it is showing.

| Tab | What it answers |
| --- | --- |
| Outlook | What to expect each day: forecast, likely range, chance of exceeding 50 and 100, and a flag |
| Observed history | What the air has been like, by pollutant |
| How reliable is it? | The live record, the 2026 back-test and how good the flags were |
| About the model | How it works and what it relies on |

**Deploy on Streamlit Community Cloud:** create an app from this repository, branch
`main`, main file `app.py`. No secrets are needed.

## Continuous integration

`.github/workflows/tests.yml` runs on every push: the unit tests, lint and format
checks, the dashboard tests, and a job that verifies the locked dataset, re-runs the
whole pipeline and re-runs the notebook.

## Attribution

Weather and air-quality forecasts by Open-Meteo.com (CC BY 4.0), including CAMS data
from the Copernicus Atmosphere Monitoring Service.
