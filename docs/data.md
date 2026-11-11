# Data

Everything the models use is public, downloaded by code, checksummed, and frozen
before modelling. This page says what is collected, why, and how to rebuild it.

## Sources

| Source | What it provides | Period | Used for |
| --- | --- | --- | --- |
| **NAPS** (Environment and Climate Change Canada) | Hourly PM2.5, ozone, NO₂, SO₂ at Toronto West, station 060430 | 2020–2024 | The AQI and pollutant inputs |
| **Air Quality Ontario** | The same monitor (station 35125), provisional readings | 2025 onward | The AQI and pollutant inputs |
| **ECCC climate-hourly**, Pearson airport (6158731) | Temperature, humidity, wind speed and direction, pressure, dew point, visibility, weather remarks | 2020 onward | Origin-day weather; exploration |
| **Open-Meteo Previous Runs API** | The weather forecast as it stood 1–7 days before each day | 2024 onward | Forecast-weather inputs |
| **Open-Meteo Air Quality API (CAMS)** | Modelled PM2.5, ozone and aerosol optical depth | Aug 2022 onward | The smoke-aware challenger |

## What is built

`data/processed/daily_aqi_latest.csv` has one row per calendar day from 2020-01-01:

- **The target.** Hourly readings become daily pollutant sub-scores under the US EPA
  2024 rules; the daily AQI is the highest of the four. A day needs all four
  pollutants with enough valid hours; otherwise its AQI is left missing. Details:
  [AQI calculation](reference/aqi_calculation.md).
- **Origin-day weather.** Daily means of temperature, humidity, wind speed and
  pressure (at least 18 valid hours).
- **Extra weather** (added November 2026): dew point, mean and minimum visibility,
  the daily wind vector (`wind_u_kmh`, `wind_v_kmh`, which keep direction and
  strength together), and the number of hours with **smoke** or **haze** in the
  airport's weather remarks.
- **Same-day pollutant signals** (added November 2026): evening PM2.5 (18:00–24:00)
  and afternoon ozone (11:00–19:00). The daily AQI is final a day late because ozone
  is averaged over 8-hour windows that run past midnight, but these readings are
  already complete when a forecast is issued.

Two forecast archives sit beside it:

- `forecast_weather.csv`: for each day and each lead of 1–7 days, the daily mean
  forecast of temperature, humidity, wind speed and pressure at Pearson. Because it
  stores what each forecast *said at the time*, a back-test sees exactly what a real
  forecast would have seen.
- `cams_daily.csv`: daily mean and peak PM2.5, peak ozone and mean aerosol depth from
  CAMS at the monitor. **Caveat:** the public archive keeps only each run's first
  hours, so historical values are near-term quality at every lead. Back-tests that
  use them are an upper bound on live skill.

Both archives are append-only: an update fetches only the days after the last stored
date and logs every download in `forecast_inputs.manifest.json`.

## Rules that protect the results

- Missing AQI is never filled in. Missing weather is filled only inside a model,
  using training data.
- NAPS takes precedence through 2024; Ontario readings are appended after it and
  flagged as not finally verified. Conflicting duplicate dates are quarantined.
  Details: [Ontario extension](reference/ontario_extension.md),
  [source comparison](reference/source_comparison.md).
- The dataset is validated and **locked** by checksum before modelling. Every report
  records the lock it was built from, and the pipeline refuses to mix versions.
  Details: [data contract](reference/data_contract.md).

## Rebuild the dataset

Needs network access to the sources above (about two minutes):

```bash
python -m airquality data
```

Review the new manifest (coverage, quarantined dates, source changes), then freeze it
and regenerate every result:

```bash
python -m airquality lock
```

```bash
python -m airquality pipeline
```

```bash
python -m airquality notebook
```

Open-Meteo's free API is rate-limited. If an update is refused, wait and run `data`
again; it resumes from the last stored day.

## What was tried and left out

- **Visibility, dew point, wind vector and smoke hours as model inputs.** They did
  not reduce validation error once same-day pollutant readings were in, so they are
  kept for analysis only. Smoke hours are too rare (19 days in seven years) to learn
  from, but they explain 15 of the 19 days above AQI 100.
- **Forecast rain, cloud, sunshine and wind direction.** Not collected: the
  provider's rate limit made a multi-year pull impractical in this revision, and the
  archive has no boundary-layer height. Worth revisiting.

## Licences

NAPS and ECCC weather: Open Government Licence – Canada. Air Quality Ontario: subject
to its own terms and disclaimer. Open-Meteo and CAMS: CC BY 4.0, attribution required.
