# Data requirements

## Forecast input

`forecast.py` consumes a local CSV with `Date` (ISO calendar date recommended) and `AQI` (finite non-negative observed numeric target). Supply one observation per consecutive day. Dates are sorted, but duplicates, times, missing dates, and missing targets are errors. Extra columns are ignored so same-day pollutants and future observed weather cannot enter the forecast features.

The target must have a consistent, documented definition. If experimenting with the original derived index, label it accordingly: its construction is not validated against the official standard. Do not use whole-series median-imputed target values as observed evaluation labels.

## Original notebook files

These files are absent from the repository:

| Local path | Expected contents |
| --- | --- |
| `data/climate/climate*.csv` | `Date/Time`, `Year`, `Month`, `Max Temp (°C)`, `Min Temp (°C)`, `Heat Deg Days (°C)`, `Cool Deg Days (°C)`, `Total Precip (mm)` |
| `data/particles/PM25.csv`, `SO2.csv`, `NO2.csv`, `NOx.csv`, `NO.csv`, `O3.csv` | Hourly pollutant exports, all under `data/particles/` |
| `data/processed_df` | Intermediate CSV reloaded before feature engineering, with `Date`, `AQI`, and explanatory columns |

The pollutant loader expects `Date` formatted day/month/year, `Station ID`, `Pollutant`, and hourly columns beginning with `H`. It replaces sentinels `9999` and `-999` and computes daily averages. The notebook merges pollutant exports on generated row IDs and dates; verify station identity and date uniqueness before relying on that join.

The processed-file export is commented out while its subsequent import is active. Restoring raw files alone does not resolve every execution dependency. Create and inspect the intermediate explicitly before later notebook sections.

## Provenance needed for new results

Record download URLs, access dates, station IDs and coordinates, units, timezone/day boundaries, missing-hour coverage rules, and reuse terms. The notebook does not establish these sufficiently to reconstruct the exact downloads; no station or source URL has been guessed here.

For the index, document averaging periods, concentration precision, breakpoint version, and missing-component handling. Using the same daily average for every pollutant does not establish an official EPA AQI: ozone and particle pollution use different averaging requirements. References: [EPA/AirNow index guidance](https://www.airnow.gov/aqi/aqi-basics/using-air-quality-index/) and [technical reporting guidance](https://www.airnow.gov/publications/air-quality-index/technical-assistance-document-for-reporting-the-daily-aqi/).

Local data, models, and default run outputs are ignored by Git. Publish source observations only with permission to redistribute and appropriate attribution.
