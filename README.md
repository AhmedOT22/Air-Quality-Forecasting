# Toronto Air Quality Forecasting

**Daily AQI forecasts for Toronto West, 1–7 days ahead** · Python · scikit-learn · pandas · Streamlit · GitHub Actions

An end-to-end forecasting project that reconstructs a four-pollutant daily AQI from public monitoring data, compares leakage-aware time-series models, publishes scheduled forecasts, and measures their performance once observations become available.

**Explore:** [Analysis notebook](AirQuality.ipynb) · [Streamlit dashboard source](app.py) · [Latest operational forecasts](reports/operational/latest_forecast.csv) · [Prospective performance](reports/operational/metrics.csv)

> **Scope:** This is an experimental, station-level reconstruction using **EPA 2024** breakpoints for PM2.5, O3, NO2 and SO2—not an official Toronto AQI, Canadian AQHI, or health advisory. A public hosted dashboard has not yet been verified.

## Results

The selected model is **Ridge regression (alpha = 1)**, with a separate direct estimator for each forecast horizon. Selection used expanding 2022–2023 validation and 2024 tuning; the 2025 period was excluded from this selection procedure.

| 2025 retrospective evaluation | Eligible pairs | Ridge MAE | Persistence MAE | MAE reduction |
| --- | ---: | ---: | ---: | ---: |
| **1-day horizon** | 314 | **10.838** | 14.854 | **27.0%** |
| **7-day horizon** | 306 | **12.160** | 16.376 | **25.7%** |

MAE is measured in AQI points on identical eligible dates for each comparison. These are **retrospective** results, not live accuracy claims. Earlier periods were inspected during development, and the later data include provisional observations and source changes. See [evaluation protocol](docs/workflow.md) and [reproducible results](reports/workflow/).

## System overview

```text
NAPS / Ontario pollution + ECCC Pearson weather
                       |
              Validated pandas ETL
         (units, coverage, gaps, AQI)
                       |
           Locked research snapshot
                       |
    Chronological folds -> tuning -> 2025 evaluation
                       |
        Selected Ridge, 1–7-day horizons
                       |
      GitHub Actions scheduled refresh
                       |
   Immutable forecasts + matured observations
                       |
      Prospective scoring + Streamlit UI
```

**Engineering highlights**

- **Reproducible preparation:** versioned ETL contract, provenance manifests, checksums, quarantined conflicts, and explicit missing calendar days. AQI targets are never imputed.
- **Leakage-aware forecasting:** lag availability accounts for cross-midnight ozone windows; preprocessing is fit on training periods only; future measured weather is not used.
- **Baseline-driven selection:** direct autoregression, Ridge and random forests compared against persistence and weekly-naive forecasts on matched samples.
- **Operational monitoring:** scheduled refresh twice daily, input-freshness gates, first-issuance forecast history, matured-observation scoring, rolling error diagnostics and model-version tracking.
- **Experimental extensions:** nominal 90% residual intervals and an Open-Meteo forecast-weather Ridge challenger, monitored separately from the approved model.

The primary model is not automatically retuned or replaced by the challenger. Nominal **90%** prediction intervals achieved only **79–87%** retrospective coverage; their calibration is not established at the advertised nominal level.

## Data and evaluation design

The locked research snapshot covers **January 1, 2020–October 30, 2026** (2,495 calendar days; 2,358 complete AQI targets). NAPS supplies the historical pollution archive through 2024, Ontario extends the same station's observations, and ECCC Pearson supplies weather. The fixed four-pollutant AQI is calculated with EPA 2024 breakpoints; CO and PM10 are excluded.

| Stage | Training / selection | Evaluation |
| --- | --- | --- |
| Candidate comparison | Expanding history through 2021 and 2022 | 2022 and 2023 |
| Hyperparameter tuning | History through 2023 | 2024 |
| Final retrospective assessment | Frozen selection fitted through 2024 | 2025 |
| Forward forecasts | Refit on available, matured history | Following 7 dates |

The [notebook](AirQuality.ipynb) presents the ten-stage research workflow. Its committed [forecast snapshot](reports/workflow/forecast.csv) is dated and **must not be mistaken for the latest live forecast**. The [operational ledger](reports/operational/) holds newer scheduled issuances and subsequent outcomes. Same-day estimates are excluded from strictly prospective metrics.

## Run locally

Python **3.11** is the reference CI environment. Run from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
python -m pip install -r requirements-tested.txt

python etl_contract.py
python workflow.py
python -m unittest discover -s tests -v
```

For the notebook or dashboard:

```bash
python -m pip install -r requirements-notebook.txt
jupyter lab AirQuality.ipynb

python -m pip install -r requirements-app.txt
python -m streamlit run app.py
```

The notebook defaults to reading **validated, committed experiment reports**; set `RECOMPUTE_MODELS = True` in its first code cell to recompute the model comparison, tuning, evaluation and refit. To refresh research inputs, review [the ETL contract](docs/etl_contract.md) before deliberately renewing the snapshot lock. To run a fresh operational issuance locally, use `python operations.py`; stale or missing inputs block publication.

## Documentation

| Reference | Details |
| --- | --- |
| [Experiment protocol](docs/workflow.md) | Splits, feature availability, candidates, selection and evaluation |
| [ETL contract](docs/etl_contract.md) · [Data sources](docs/extended_data.md) | Input integrity, provenance and research snapshot renewal |
| [AQI calculations](docs/data.md) · [Source comparison](docs/source_comparison.md) | Pollutant transformations, standards and source limitations |
| [Operations](docs/operations.md) | Refresh schedule, immutable issuances, monitoring and uncertainty |
| [Dashboard](docs/dashboard.md) | Views, report freshness, setup and fallback behavior |
| [Final audit](docs/audit.md) | Reported checks, limitations and remaining release work |

## Limitations and next steps

This is **one monitoring site**, using airport weather as a proxy. Instrument/source changes, missing periods, provisional Ontario observations and sparse high-pollution events constrain generalization. Archived forecast-weather inputs do not perfectly reproduce historical provider publication vintages; overlapping forecast errors are not independent. The current prospective record is too small to establish reliable live skill.

**Next priorities:** deploy and visually verify the public Streamlit dashboard, accumulate genuinely prospective scores, and reassess interval calibration and challenger performance on more observations. The repository's [audit](docs/audit.md) documents the tests reported as passing; those results are not a substitute for independent external validation.

**Sources:** Environment and Climate Change Canada, NAPS, Meteorological Service of Canada and Government of Ontario (research snapshot accessed October 31, 2026). NAPS data are distributed under the [Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada). Open-Meteo forecast weather is credited in the [operations documentation](docs/operations.md).

Developed by [Ahmed Ouazzani](https://github.com/AhmedOT22).
