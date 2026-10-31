# Streamlit dashboard

The new app entry point is `app.py`. It is read-only: opening it or pressing
Refresh does not retrain models, change ETL snapshots, or write monitoring history.

```bash
python -m pip install -r requirements-app.txt
python -m streamlit run app.py
```

`requirements-app.txt` pins the tested UI dependencies alongside the existing tested
modelling environment. `requirements.txt` also includes Streamlit/Plotly so a normal
Streamlit Community Cloud deployment can install them. Select this repository,
branch `main`, entry point `app.py`. No API keys or secrets are required. Creating the
app source and passing tests does not itself create a hosted Community Cloud URL.

## Views

- **Forecast outlook:** primary Ridge, experimental bounds, optional weather-aware
  challenger, 1–7-day selector, dated table and CSV download. Same-day h1 is identified.
- **Observed history:** real daily AQI, preserved gaps and pollutant sub-indices;
  last 90 days, last year or all observations since 2020. Frozen component detail
  explicitly states its snapshot endpoint; new monitored observations extend total AQI.
- **Performance:** prospective counts/errors only after truth matures; rolling
  diagnostics and deterioration flags; separately labelled 2025 retrospective scores
  and exploratory weather-challenger/interval evaluations. Empty scores mean waiting.
- **About the model:** location, model, preparation rules, source quality, schedule,
  report revision and provenance. No unsupported neighbourhood filters are fabricated.

## Report access and freshness

Latest published mode resolves public GitHub main to a commit SHA, then fetches all
operational files from that exact revision. The app caches public reads for five
minutes. Refresh clears that cache. This avoids mixing files while an automated
publication is in progress and supports hosted apps whose checked-out CSVs are older.

If required remote files cannot be read, the app uses the bundled snapshot with a
prominent notice. Snapshot mode works offline. Both modes calculate freshness at
viewing time: yesterday's fixed-EST origin and an update within 26 hours are required.
A report marked successful at generation is not shown as current indefinitely.
Blocked refreshes retain historical predictions with a warning rather than hide
failure behind a green status. Multiple releases on one origin are separated by
model version; the newest version is displayed without averaging their predictions.

The dashboard uses existing reports. It does not contact the pollutant/weather APIs
or invent missing observations, live accuracy, forecast intervals or health advice.
The experimental nominal 90% bands achieved 79–87% retrospective coverage, which is
visible beside the chart. Challenger forecasts remain opt-in and clearly labelled.

## Verification

`tests/test_dashboard.py` checks data freshness, blocked status, remote fallback,
version selection and real Streamlit interactions (horizon, interval/challenger
controls, history range and pollutant). UI tests run in a separate CI job with
`requirements-app.txt`; core-only environments skip UI integration tests while still
running data-access tests. Tests use `AQI_DASHBOARD_OFFLINE=1` and no live requests.

The app also passes a local-only Streamlit startup and HTTP health check. A browser
screenshot was not verified in this workspace; rendered elements and widget behavior
were verified through Streamlit AppTest. For an explicit local startup without
external-IP discovery, use:

```bash
python -m streamlit run app.py --server.address 127.0.0.1 --browser.serverAddress 127.0.0.1
```
