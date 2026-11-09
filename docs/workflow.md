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
index-only random forest, forest with weather, gradient boosting, persistence and
weekly naive. The
linear autoregression is a classical lag regression, not a claim to have run ARIMA,
SARIMA, ETS or Prophet. This bounded candidate set does not establish a globally
optimal model. Forests use 100 trees, minimum leaf size 5 and seed 42.

Gradient boosting (scikit-learn `HistGradientBoostingRegressor`: absolute-error loss,
learning rate 0.03, 300 iterations, 7 leaves, minimum leaf 20, seed 42) was added in
November 2026. It handles missing weather natively. Disclosure: a first setting
(learning rate 0.05, 15 leaves) was tried and its 2025 scores were seen before the
shallower setting was adopted. The change was justified by its better 2022–23 folds
(12.80 vs 12.90 MAE), and boosting did not win selection under either setting, so
the frozen Ridge selection and its 2025 results are unchanged. `boosting_challenger.csv`
reports boosting tuned on 2024 beside Ridge on 2025 for information only.

Choose the family using mean MAE with equal fold/horizon weights. Tune the winning
family on 2024: Ridge alpha 1/10/100, forest leaf size 5/10/20 or boosting minimum
leaf 10/20/40. AR/baselines are
fixed; both baselines can still win at tuning. Freeze the selected configuration
before evaluating 2025. The same configuration is used for every horizon, but each
horizon has its own fitted direct estimator. Candidate features and settings do not
change in response to 2025 scores.

Evaluate the selection and baselines on identical eligible pairs per horizon.
Report training MAE, evaluation MAE/RMSE, persistence skill, monthly error and error
by observed category with counts. Training errors are optimistic diagnostics, not
validation scores; differing conditions and source precision also affect the gap.
Overlapping forecasts are dependent. No statistical significance is claimed for
these comparisons. Interval coverage is assessed separately on 2026 data in
[the operational protocol](operations.md). All periods have source-quality limitations, and 2022–2024 were
already inspected. 2025 is excluded from this model-selection procedure, not claimed
to be permanently untouched after publication. Prospective monitoring is implemented;
its evidence must accumulate after issuance.

Finally refit the frozen selection on all information available at the latest
completed origin. Forecast the next seven dates, not historical fitting rows. Stop
if required latest AQI lags are missing. The dated output carries its origin and
input checksum. The automatic scheduler publishes separate operational reports.
A health warning system is not implied. Future measured weather is never treated as known.

Outputs are in `reports/workflow/`; run `python workflow.py` to regenerate them.
`python explain.py` writes grouped permutation importance for the selected model
(fitted through 2024, scored on 2025) to `reports/explain/`; correlated AQI lags share
credit, and importance describes model reliance, not causal effects.
The notebook normally displays the already executed outputs, verifying their lock.
Set `RECOMPUTE_MODELS = True` to repeat the entire modelling run from the notebook.
