# Evaluation design

## Interpreting the original analysis

The notebook constructs its target from pollutant concentrations and also includes same-day PM2.5, NO₂, and ozone in the predictors. These explain index relationships, but would not be available before the predicted day. TimeSeriesSplit alone does not fix feature availability.

Other limitations in the saved exploration:

- An 80/20 random split mixes past and future observations for supervised tuning.
- Missing values, including targets, are filled with whole-series statistics before evaluation.
- Section 6.3 fits supervised models on all `X,y` and evaluates on some of the same rows. These are in-sample reconstruction scores. Statistical models use a different training setup, so the table is not a fair model ranking.
- The recursive example holds environmental predictors constant, advances the month every day, and starts with an incorrect next-day lag state. The final plotting cell refers to undefined outer variables.
- The exported and subsequently overwritten `rf_model` is distinct from the tuned `best_rf_model` used in evaluation.

The notebook remains an original exploration with limitations documented in this file and the README. Its outputs have not been silently relabelled as corrected results.

## Standalone benchmark

1. Validate and sort consecutive daily observations; do not impute evaluation targets.
2. Reserve the final `test_days` observations chronologically.
3. Fit a fixed Random Forest on training rows. Features are AQI lags 1, 2, 3, 7, 14 and sine/cosine day-of-year terms known in advance. No hyperparameter selection uses holdout data.
4. At each eligible origin, forecast recursively, using predictions rather than unrevealed actuals in later lags.
5. Compare persistence (last known observation) and seasonal naïve (repeat the latest observed week) on identical origins/targets for each horizon.
6. Save metrics, prediction rows, and run metadata. Refit on all observations only afterwards for a separate future forecast.

Defaults are 200 trees, minimum leaf size 3, seed 42: fixed starting choices, not optimal tuned parameters. Actual targets are assumed available at each origin; reporting delays would require another availability constraint.

Only complete trajectories are evaluated. Therefore, the final `horizon - 1` days do not have one-day predictions from later origins. Overlapping trajectories are dependent: counts are forecast counts, not independent trials. The plot shows one-day predictions only. No confidence intervals, causal effects, or calibrated public-health categories are claimed.

## Validation status

Tests use deterministic artificial daily series and the package versions in `requirements-tested.txt`. Changing all held-out labels must leave the first complete forecast trajectory unchanged. These fixtures validate behavior, not forecast accuracy.

No corrected Toronto MAE/RMSE is available until source observations, station metadata, and the target definition are verified. If the model loses to persistence, report that result.
