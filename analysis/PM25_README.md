# Supplementary concentration analysis

The main project forecasts AQI; see [the main README](../README.md).
This document retains the separate PM2.5 concentration experiment. Its scores are
not AQI forecasting scores and do not demonstrate a source-only improvement.

# Toronto PM2.5 Forecasting

Forecasting daily mean **PM2.5 concentration at Toronto West**, using official
NAPS pollution observations and Environment and Climate Change Canada weather
observations. The reproducible snapshot covers **2020–2024**.

[Executed notebook](AirQuality.ipynb) · [Data provenance](docs/data.md) ·
[Evaluation design](docs/evaluation.md) · [2024 results](reports/2024/metrics.csv) ·
[2023 results](reports/2023/metrics.csv)

![2024 forecasting error by horizon](reports/2024/horizon_errors.png)

## What changed

The current pipeline replaces the original undocumented CSV inputs and derived AQI
with quality-assured NAPS PM2.5 and ECCC station weather observations. It forecasts
concentration in **µg/m³**, not an official AQI/AQHI or public-health risk score.

- Station IDs, methods, source URLs, retrieval times, and checksums are recorded.
- Daily targets require at least 18 valid hours. Missing targets stay missing.
- Complementary instrument methods are combined by hour; conflicting readings fail validation.
- Direct 1–7 day forecasts use pollution history and completed-origin-day weather.
- Chronological 2023 and 2024 evaluations compare Ridge, Random Forest, persistence,
  and weekly seasonal naïve on identical eligible pairs at each horizon.
- A pollution-only forest provides a comparison for the weather-assisted forest.

## Results

MAE is in µg/m³; lower is better. These are retrospective benchmarks with fixed
model settings, not real-time operational scores or estimates of health risk.

| Evaluation year | Horizon | Eligible forecasts | Ridge + weather | Forest + weather | Forest, pollution only | Persistence | Weekly naïve |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2023 | 1 day | 335 | 3.935 | 4.065 | 4.247 | 4.590 | 6.925 |
| 2023 | 7 days | 326 | 4.921 | 4.859 | 4.825 | 7.008 | 7.008 |
| 2024 | 1 day | 355 | 2.301 | 2.318 | 2.477 | 2.727 | 4.340 |
| 2024 | 7 days | 348 | 3.233 | 3.250 | 3.185 | 4.353 | 4.353 |

The one-day Ridge model reduced MAE relative to persistence by **14.3% in 2023**
and **15.6% in 2024**. Adding weather helped the forest's one-day MAE in both years,
but did not beat the pollution-only forest's seven-day MAE. There is no universal
winner across models, metrics, and horizons.

2023 has substantially larger errors than 2024. The model settings were not tuned
on either evaluation year. Because 2023 observations enter training for the 2024
benchmark, these are two chronological exercises, not independent replications.
Full MAE, RMSE, skill scores, predictions, and monthly errors are committed in
`reports/2023/` and `reports/2024/`.

## Data quality

The prepared snapshot has **1,827 calendar days**, **1,801 observed PM2.5 targets**,
and **26 missing targets**. Each weather feature has 1,826 qualifying daily means.
Missing dates are retained so a one-day lag always means one calendar day.

- **Pollution:** NAPS station `060430`, Toronto West, 125 Resources Road.
- **Weather:** ECCC climate station `6158731`, Toronto Intl A (Pearson).
- **Time:** local standard time, UTC−5, without daylight-saving shifts.
- **Scope:** one monitoring site; it does not represent every Toronto neighbourhood.

The two stations are approximately 7.9 km apart; airport weather is a proxy for
conditions at the pollution site. NAPS method codes change during the period;
this transition is recorded, not assumed to be perfectly homogeneous.

## Run the complete pipeline

Use Python 3.11 or newer from the repository root:

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-tested.txt

# Download official raw observations, validate, and rebuild the prepared dataset
python data_sources.py --target PM25

# Evaluate 2024, using only earlier observations for fitting
python forecast.py --input data/processed/daily_pm25.csv --output reports/2024

# Evaluate 2023, using only 2020–2022 for fitting
python forecast.py --input data/processed/daily_pm25.csv --end-date 2023-12-31 --test-days 365 --output reports/2023

python -m unittest discover -s tests -v
```

The small prepared snapshot and source manifest are committed, so the forecasting
commands also work **offline** immediately after installation. Raw national files
are cached under ignored `data/raw/`. Downloads retry transient failures and reject
HTML responses, unexpected schemas, cache checksum changes, and truncated weather responses.

Providers can revise data under the same URL. To intentionally refresh source bytes,
run `python data_sources.py --target PM25 --refresh`, then regenerate both benchmarks. Results
may change; compare manifests rather than treating a refreshed download as identical.

For Jupyter:

```bash
python -m pip install -r requirements-notebook.txt
jupyter lab AirQuality.ipynb
```

The notebook runs preparation checks, exploratory plots, both benchmarks, and
interpretation from the same Python functions. It does not maintain a second model pipeline.
Its cells were executed sequentially with captured real outputs using
`python scripts/execute_notebook.py`. This in-process check avoids sockets; normal
Jupyter kernel startup could not be verified in the execution environment.

## Outputs and structure

| Path | Purpose |
| --- | --- |
| `data_sources.py` | Official downloads, caching, station validation, hourly quality rules, daily preparation |
| `forecast.py` | Feature availability, direct forecasting, chronological evaluation, reports |
| `data/processed/daily_pm25.csv` | Frozen station-specific daily snapshot with coverage counts |
| `data/processed/daily_pm25.manifest.json` | Source URLs/checksums, stations, methods, quality summary |
| `AirQuality.ipynb` | Current executed analysis |
| `reports/2023/`, `reports/2024/` | Published retrospective benchmark outputs |
| `tests/` | Source-format, leakage, imputation, missingness, and report integration tests |
| `notebooks/legacy/` | Archived original notebook/formulas; not the current pipeline |

Each report directory includes `metrics.csv`, `backtest.csv`, `monthly_metrics.csv`,
`run.json`, `backtest.png`, `horizon_errors.png`, and `forecast.csv`. The latter
projects beyond its historical archive endpoint, **not today's date**.

## Limits

The benchmarks assume finalized observations are available after the completed
origin day; publication delays and subsequent archive revisions are not simulated.
Missing pollution history reduces eligible forecasts, and gaps can be non-random.
Forecast errors at overlapping origins are dependent. No uncertainty intervals
or validated extreme-event warning capability are claimed.

The original exploration is archived with its saved outputs. Its old AQI accuracy
claims are superseded and are not comparable with these concentration forecasts.

## Attribution

Source observations: **Environment and Climate Change Canada**, National Air Pollution
Surveillance Program and Meteorological Service of Canada, accessed October 31, 2026.
NAPS data: [Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada).
Weather: [ECCC data terms](https://climate.weather.gc.ca/prods_servs/attachment1_e.html).
Prepared values and plots are derived from these sources; no government endorsement is implied.

Developed by [Ahmed Ouazzani](https://github.com/AhmedOT22).
