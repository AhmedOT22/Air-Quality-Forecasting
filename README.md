# Toronto AQI forecasting

Use historical pollution and weather observations to forecast **upcoming daily AQI**
at Toronto West, one to seven days ahead. The main analysis is
[AirQuality.ipynb](AirQuality.ipynb). Its workflow ends with genuinely subsequent
forecast dates; historical evaluation supports that deliverable.

## Data and locked preparation

The prepared snapshot starts **January 1, 2020**. NAPS pollution is retained through
2024; Ontario observations extend the same four pollutants through October 31, 2026.
ECCC Pearson supplies weather. The daily modelling input ends on the latest completed
EST day, **October 30, 2026**: 2,495 calendar days, 2,358 complete AQI targets.

The target uses fixed **EPA 2024** breakpoints for PM2.5, O3, NO2 and SO2, with EPA
2018 retained for comparison. This is a four-pollutant station reconstruction, not
an official city AQI or Canadian AQHI. CO and PM10 are excluded. No government
endorsement or health-warning capability is implied.

The ETL handles units, dates, sentinels, short rows, instrument conflicts, duplicate
dates, hourly coverage and cross-midnight ozone windows. It preserves calendar gaps
and never imputes AQI. Ontario-containing values are explicitly flagged as not finally
verified. Source URLs, times, hashes, overlap diagnostics and quarantines are recorded.

**ETL contract version 1 is locked.** Modelling verifies the daily, manifest and hourly
checksums before running. A refresh requires review, explicit lock renewal and report
regeneration. See [ETL contract](docs/etl_contract.md), [extended data](docs/extended_data.md),
[formulas](docs/data.md) and [source assessment](docs/source_comparison.md).

## Main analytical flow

1. Define the AQI forecasting objective and success metrics.
2. Acquire and assess historical and recent data.
3. Validate the locked cleaning, integration and AQI transformations.
4. Declare chronological training, validation and test boundaries.
5. Explore distributions, relationships and time-series patterns on 2020–2021.
6. Build availability-aware features and training-only preprocessing.
7. Compare autoregression, Ridge, forests and simple baselines in 2022–2023.
8. Tune the winning family on 2024 and freeze the selected configuration.
9. Evaluate on 2025, with overfitting and monthly/category error diagnostics.
10. Refit on available history and forecast the following seven dates.

AQI inputs end at origin t−1 because ozone windows can include the following morning.
Weather uses completed origin t. Models never use future measured weather or same-day
components to reconstruct their prediction target. Every training label respects its
availability boundary. Models share identical eligible pairs per horizon.

The classical candidate is direct linear autoregression on AQI history; ARIMA, SARIMA,
ETS and Prophet are not claimed to have been run in this new experiment. Candidate
forests use 100 trees and seed 42. The limited search is intentional; no claim of global
optimality is made. See [full evaluation protocol](docs/workflow.md).

## Results and upcoming forecast

Rolling candidate comparison selected Ridge with weather. The 2024 tuning comparison
selected **Ridge alpha 1**, before the 2025 evaluation.

| 2025 evaluation | Eligible pairs | Selected MAE | Persistence MAE | MAE reduction |
| --- | ---: | ---: | ---: | ---: |
| 1 day | 314 | 10.838 | 14.854 | 27.0% |
| 7 days | 306 | 12.160 | 16.376 | 25.7% |

Errors are AQI points. These are same-source baseline comparisons, not evidence of
superiority over the original absent raw files. 2022–2024 were previously inspected;
2025 is excluded from this procedure's selection but is not permanently untouched
once published. Source precision and provisional quality change across this period.
Training/validation gaps alone do not prove overfitting absent or present.

The selected configuration is separately refit through the completed origin
**October 30, 2026**, producing forecasts for **October 31–November 6, 2026**.
Read [forecast.csv](reports/workflow/forecast.csv), the executed notebook and
[run metadata](reports/workflow/run.json). This is a dated forecast snapshot;
scheduled refresh/publication is not configured. No calibrated intervals are claimed.

## Run

Python 3.11+, from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-tested.txt

# Verify the locked input and run the complete modelling experiment offline.
python etl_contract.py
python workflow.py
python -m unittest discover -s tests -v

# Notebook dependencies and execution with actual captured outputs:
python -m pip install -r requirements-notebook.txt
python scripts/execute_notebook.py
# Or: jupyter lab AirQuality.ipynb
```

The notebook defaults to displaying executed reports with a matching lock. Set
`RECOMPUTE_MODELS = True` to regenerate the full experiment from its cells. Its
execution check uses sequential in-process IPython because this environment blocks
kernel sockets; Jupyter kernel startup itself is not verified.

To refresh observations deliberately:

```bash
python extend_data.py --refresh
# Review the resulting provenance and quality report before renewing the lock.
python etl_contract.py --lock
python workflow.py
python scripts/execute_notebook.py
```

Raw national/provider downloads are cached outside Git. The committed normalized
hourly and daily snapshots allow offline modelling. Provider revisions may prevent
future retrieval of identical raw bytes; pinned historical hashes fail closed.

## Files

| Path | Purpose |
| --- | --- |
| `AirQuality.ipynb` | Main ten-stage analysis and forward forecasts |
| `etl_contract.py` | Data validation and explicit snapshot lock |
| `extend_data.py`, `aqi_data.py`, `data_sources.py`, `aqi.py` | Shared ETL and AQI formulas |
| `workflow.py` | Expanding folds, bounded tuning, evaluation and forward refit |
| `reports/workflow/` | Current selection, diagnostics, evaluation and future forecasts |
| `data/processed/*latest*` | Extended hourly/daily inputs, manifest and lock |
| `forecast.py`, `reports/aqi/2023/`, `reports/aqi/2024/` | Earlier fixed-setting historical benchmarks |
| `analysis/PM25.ipynb`, `reports/2023/`, `reports/2024/` | Supplementary PM2.5 concentration analysis |
| `notebooks/legacy/` | Original exploration preserved for history |

## Limitations and attribution

One pollution site, an airport weather proxy, instrument changes and missing periods
limit generalization. Ontario warns that unverified observations should not be used
in published documents; experimental extension results are distinguished from the
quality-assured archive. Additional publication delays and archive revisions are not
simulated. Sparse high-pollution events and overlapping forecasts limit conclusions.
Prospective monitoring, forecast-weather features and uncertainty calibration remain
future work, not completed capabilities.

Source observations: Environment and Climate Change Canada, NAPS, Meteorological
Service of Canada and Government of Ontario, accessed October 31, 2026. NAPS data
use the [Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada).

Developed by [Ahmed Ouazzani](https://github.com/AhmedOT22).
