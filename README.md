# Toronto Air Quality Forecasting

**Daily AQI forecasts for Toronto, 1–7 days ahead — trained, evaluated and published automatically.**

Python · pandas · scikit-learn · Streamlit · GitHub Actions

![Dashboard: observed AQI and the upcoming 7-day forecast](docs/images/dashboard.png)

An end-to-end forecasting system: it builds a daily Air Quality Index from public
government monitoring data, selects a model with leakage-free time-series validation,
then issues new forecasts twice a day and scores each one against what actually happened.

## Results

The selected model, **Ridge regression** (one model per horizon), was chosen on
2022–2024 data and then evaluated once on the held-out year **2025**:

| Horizon | Ridge MAE | Persistence MAE | Error reduction |
| --- | ---: | ---: | ---: |
| 1 day | **10.8** | 14.9 | **27%** |
| 3 days | **12.5** | 15.6 | **20%** |
| 7 days | **12.2** | 16.4 | **26%** |

MAE is in AQI points on 306–314 matched dates per horizon. "Persistence" repeats the
latest known AQI — the standard baseline a forecast has to beat. Ridge beats it at every
horizon from 1 to 7 days. Full tables: [`reports/workflow/`](reports/workflow/).

## How it works

```text
Federal (NAPS) + Ontario pollution data, ECCC weather
                       │
        Validated ETL → daily 4-pollutant AQI (EPA 2024)
                       │
       Checksummed, locked research snapshot
                       │
  Model comparison (2022–23) → tuning (2024) → final test (2025)
                       │
     GitHub Actions: refresh data twice daily, issue 7-day forecast
                       │
  Forecast ledger (data branch) → score once observations arrive
                       │
                Streamlit dashboard
```

**Engineering highlights**

- **No look-ahead leakage.** Features only use data that would have been available at
  forecast time, including the one-day delay before ozone-based AQI is final. Scaling
  and imputation are fitted on training data only, and tests assert that changing
  future values never changes a past prediction.
- **Baseline-driven model selection.** Linear autoregression, Ridge and random forests
  were compared against persistence and weekly-repeat baselines on identical dates,
  using expanding yearly folds rather than random splits.
- **Reproducible data.** A versioned ETL contract, SHA-256 checksums and source
  manifests lock the research snapshot. Missing AQI is never imputed.
- **Production behaviour.** Each forecast is recorded once and never overwritten,
  stale inputs block publication instead of silently reusing old data, and every
  forecast is tagged with the model version that produced it.
- **Tested.** 55 unit and integration tests cover AQI calculations, leakage,
  scheduling and the dashboard; CI also re-executes the analysis notebook.

## Project layout

| Path | Purpose |
| --- | --- |
| [`AirQuality.ipynb`](AirQuality.ipynb) | Research notebook: data, EDA, model selection, evaluation |
| `aqi.py`, `aqi_data.py`, `data_sources.py`, `extend_data.py` | Data acquisition and AQI calculation |
| `etl_contract.py` | Validates and locks the prepared dataset |
| `features.py`, `workflow.py` | Leakage-aware features, model selection and evaluation |
| `operations.py` | Scheduled refresh, forecast issuance and scoring |
| `app.py`, `dashboard_data.py` | Streamlit dashboard |
| `weather_model.py`, `uncertainty.py` | Experimental: weather-forecast challenger, intervals |

## Run locally

Python 3.11, from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python workflow.py                   # reproduce model selection and the 2025 test
python -m unittest discover -s tests # run the test suite
streamlit run app.py                 # open the dashboard
```

For the notebook, install `requirements-dev.txt` and run `jupyter lab AirQuality.ipynb`.

## Limitations

- **Single station.** Forecasts cover the Toronto West monitor, using Pearson airport
  weather as a proxy.
- **Not an official index.** The AQI is reconstructed with US EPA 2024 breakpoints
  from four pollutants (PM2.5, O3, NO2, SO2). It is not Canada's AQHI or a health advisory.
- **Live track record is still building.** The 2025 numbers above are a historical
  test. Live accuracy appears on the dashboard once each horizon has 30 scored forecasts.
- **Experimental extras.** The nominal 90% intervals reached only 79–87% coverage
  historically, and the weather-forecast challenger is monitored separately and never
  replaces the main model automatically.

## Documentation

[Evaluation protocol](docs/workflow.md) · [Data & AQI calculation](docs/data.md) ·
[ETL contract](docs/etl_contract.md) · [Data sources](docs/extended_data.md) ·
[Source comparison](docs/source_comparison.md) · [Operations](docs/operations.md) ·
[Dashboard](docs/dashboard.md)

**Data:** Environment and Climate Change Canada (NAPS, Meteorological Service of Canada)
and the Government of Ontario, under the
[Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada).
Forecast weather from [Open-Meteo](https://open-meteo.com/) (CC BY 4.0).

Developed by [Ahmed Ouazzani](https://github.com/AhmedOT22).
