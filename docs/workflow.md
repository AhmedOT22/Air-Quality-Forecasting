# Forecasting experiment

The main notebook follows the approved acquisition → preparation → chronological
split → exploration → feature engineering → model comparison → tuning → final
assessment → full-history refit → future forecasting flow. Its ETL input is locked.

Initial EDA uses only 2020–2021. Candidate models fit through 2021 and validate in
2022, then fit through 2022 and validate in 2023. These are expanding annual folds,
not random partitions. Index availability is delayed one full calendar day because
of ozone windows. Every training label and predictor obeys that boundary. Imputation
and scaling are fitted within the training window; missing AQI is never imputed.

Candidates are direct linear autoregression on AQI history, Ridge with weather,
index-only random forest, forest with weather, persistence and weekly naive. The
linear autoregression is a classical lag regression, not a claim to have run ARIMA,
SARIMA, ETS or Prophet. This bounded candidate set does not establish a globally
optimal model. Forests use 100 trees, minimum leaf size 5 and seed 42. These are
separate experiments from the earlier fixed 200-tree benchmarks retained in
`reports/aqi/2023/` and `/2024/`.

Choose the family using mean MAE with equal fold/horizon weights. Tune the winning
family on 2024: Ridge alpha 1/10/100 or forest leaf size 5/10/20. AR/baselines are
fixed; both baselines can still win at tuning. Freeze the selected configuration
before evaluating 2025. The same configuration is used for every horizon, but each
horizon has its own fitted direct estimator. Candidate features and settings do not
change in response to 2025 scores.

Evaluate the selection and baselines on identical eligible pairs per horizon.
Report training MAE, evaluation MAE/RMSE, persistence skill, monthly error and error
by observed category with counts. Training errors are optimistic diagnostics, not
validation scores; differing conditions and source precision also affect the gap.
Overlapping forecasts are dependent. No significance or uncertainty coverage is
claimed. All periods have their source-quality limitations, and 2022–2024 were
already inspected. 2025 is excluded from this model-selection procedure, not claimed
to be permanently untouched after publication. Prospective monitoring is still needed.

Finally refit the frozen selection on all information available at the latest
completed origin. Forecast the next seven dates, not historical fitting rows. Stop
if required latest AQI lags are missing. The dated output carries its origin and
input checksum. Current data can be downloaded, but no automatic scheduler or health
warning system is implied. Future measured weather is never treated as known.

Outputs are in `reports/workflow/`; run `python workflow.py` to regenerate them.
The notebook normally displays the already executed outputs, verifying their lock.
Set `RECOMPUTE_MODELS = True` to repeat the entire modelling run from the notebook.
