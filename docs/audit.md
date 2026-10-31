# Final cleanup and audit

Reviewed on October 31, 2026. Scope: the locked ETL, chronological modelling,
forecast publication and scoring, Streamlit data handling, dependencies, notebook
and repository documentation. This is a code and reproducibility audit, not an
independent certification of provider measurements or forecast skill.

## Findings resolved

| Finding | Resolution |
| --- | --- |
| Production ETL guards used removable Python assertions | Explicit exceptions remain active under `python -O`; date bounds and all four component formulas are checked. |
| Scoring inferred one timestamp format for the whole ledger | Explicit ISO-8601 parsing supports mixed fractional-second precision. |
| Primary issuance could be timestamped before model fitting | Read the production issuance clock after inference. |
| Monitoring alerts omitted the model version | Include `model_id` alongside the model and horizon. |
| Charts could bridge absent operational dates or retain duplicate revisions | Normalize dates before deduplication and reindex to every calendar day. |
| Dashboard accepted infinite predictions, incomplete horizons or inconsistent dates | Reject malformed forecast bundles and future-dated refresh timestamps. |
| Deployment dependency ranges differed from tested versions | Default requirements delegate to the pinned dashboard environment. |
| Refresh triggers omitted shared ETL code and configuration dependencies | Include AQI/source modules, core requirements and selected-model metadata. |
| Completed functionality was still labelled future work | Reconcile README, notebook and method/operations documentation. |
| Dense app and operations code made maintenance harder | Format the edited modules, remove unused imports and add a small lint configuration. |

The original exploration and earlier benchmarks remain clearly labelled historical
artifacts. `forecast.py` and the source modules are shared by the current pipeline;
they are not dead code. No frozen datasets, historical reports, model selection or
past forecast ledger entries were rewritten during cleanup.

## Methodology assessment

- Objective remains upcoming daily, four-pollutant EPA 2024 AQI at Toronto West.
  The current selected model remains Ridge alpha 1, with separate direct horizons.
- Calendar gaps remain explicit. Targets are never imputed; weather imputation and
  scaling fit within training windows. Features and labels respect the ozone delay.
- Expanding candidate comparison uses 2022–2023; tuning uses 2024; 2025 is excluded
  from selection. Baselines use the same eligible pairs within each horizon.
- Forecast-weather comparisons and residual intervals have separate 2026 evidence.
  The challenger is not automatically promoted. Future observed weather is excluded.
- Operational first issuance is immutable per origin/model version. Same-day
  estimates are excluded from prospective metrics; truth must mature before scoring.

These checks found no new time-leakage defect in the reviewed feature/label logic.
They do not prove the absence of overfitting. Previously inspected periods,
provisional observations and dependent forecast errors limit the conclusions.

## Verification performed

- **58 tests passed**, including real Streamlit AppTest interactions and regression
  cases for optimized ETL validation, component formulas, mixed timestamps,
  issuance timing, calendar gaps and invalid dashboard reports.
- All 11 main-notebook code cells executed sequentially with actual captured outputs.
  This checks notebook code; it does not verify Jupyter kernel transport.
- Recomputed the full candidate comparison, tuning, 2025 evaluation and seven-day
  forecast from the locked inputs. Recomputed interval calibration and the weather
  challenger using the committed archived forecasts. Generated CSVs matched the
  committed results within `1e-10`; JSON metadata matched exactly.
- The original daily data SHA-256 remains
  `05ace9b4186bc84202a06fd84296d0f1478638d0785463afe4d80dbad0428aed`.
- Optimized-mode lock validation, Ruff checks, Python compilation, dependency checks
  and Git whitespace checks passed.
- Streamlit started on loopback and returned HTTP 200 with `ok` from its health
  endpoint. Browser screenshots and mobile visual layout were not verified here.

CI now checks core tests, dashboard interactions, lint/compilation and notebook
execution on Python 3.11. See [workflow runs](https://github.com/AhmedOT22/Air-Quality-Forecasting/actions)
for the result attached to each commit.

## Remaining release work and evidence

1. **Public hosting and visual acceptance:** deploy `app.py`, verify the public URL,
   and review desktop/mobile layouts, loading, error states and downloads in a browser.
2. **Prospective evidence:** let real outcomes accumulate. The project cannot claim
   live predictive skill merely because the software passes tests.
3. **Experimental limitations:** nominal 90% intervals achieved 79–87% retrospective
   coverage. Archived forecast-weather fields approximate original weather vintages.
   Keep both limitations visible until new evidence supports stronger claims.

One pollution station and an airport weather proxy limit geographic claims. Recent
Ontario measurements are provisional. GitHub scheduling is best effort, and full
production input artifacts expire after 90 days. These are documented operating
limits, not additional completed capabilities.
