# Source assessment for the AQI forecasting objective

The project objective is forecasting **AQI**, using the original four pollutants
(PM2.5, ozone, NO2, SO2). PM2.5 concentration forecasting is a separate analysis and
its errors are not evidence of improved AQI predictions.

## What can be compared

| Criterion | Original inputs/notebook | Replacement inputs |
| --- | --- | --- |
| Exact source identity | Raw CSVs and download URLs are absent; older descriptions name Toronto/open data and Environment Canada without sufficient identifiers | ECCC NAPS annual hourly pollutant files and GeoMet weather, exact URLs and SHA-256 recorded |
| Quality assurance | Cannot establish the original files' validation status | NAPS describes quality-assured submissions to its national archive |
| Station identity | Original processing discards station IDs and joins generated row IDs with dates | Toronto West NAPS 060430 retained, paired with ECCC 6158731 weather |
| Temporal detail | Original loader reduces every pollutant to a daily mean | Hourly inputs support pollutant-specific daily maxima and ozone 8-hour windows |
| Missing targets | Original notebook median-fills missing AQI | No target imputation; all four components required |
| Index definition | US EPA-style breakpoints, but unvalidated averaging, rounding and upper-range handling | Explicit EPA-2024-based four-pollutant reconstruction across all years; EPA-2018 comparison stored separately |
| Source-only accuracy improvement | Cannot measure without original observed inputs and an identical target/evaluation protocol | New AQI results can be compared with baselines, not claimed superior to old saved scores |

**Verdict:** NAPS is a defensible, documented source for reconstructing this AQI.
It improves the project's provenance and preparation auditability. It is not proven
to have better raw measurements than the original files: they might have come from
the same monitoring network. Better QA documentation also does not guarantee lower
prediction error. No source-only improvement percentage is claimed.

## Coverage of the replacement data

At least 18 valid hours per daily PM2.5/NO2/SO2 component; ozone additionally requires
13 of its 17 eligible daily eight-hour windows, each with at least six valid hours.
All four component indices must be present before forming AQI.

| Year | Calendar days | Complete four-component AQI days | Missing AQI days |
| --- | ---: | ---: | ---: |
| 2020 | 366 | 345 | 21 |
| 2021 | 365 | 356 | 9 |
| 2022 | 365 | 346 | 19 |
| 2023 | 365 | 308 | 57 |
| 2024 | 366 | 354 | 12 |
| Total | 1,827 | 1,709 | 118 |

SO2 has only 317 qualifying daily components in 2023. This is a real limitation of
the selected source/station, not something to hide by substituting a low pollutant
index or imputing the combined AQI. Missing periods affect forecast eligibility
and may not be representative of the full year.

## Alternatives evaluated

- **Air Quality Ontario web readings:** official monitoring provider, but its web
  disclaimer identifies unverified data. Useful for recent observations, not a
  demonstrated quality upgrade over the verified NAPS archive.
- **AirNow daily archive:** offers reported AQI/sub-indices and daily concentrations,
  useful for an independent cross-check. It is not used here as a substitute for
  quality-assured NAPS measurements, and no station-matched agreement test is claimed.
- **Ontario AQHI archive:** a different index and would change the project's target.
  It is not substituted for AQI.
- **ECCC historical weather:** retained; it already provides official station
  observations. A convenient reanalysis API is not automatically a quality upgrade.

References:

- [NAPS data collection and validation](https://www.canada.ca/en/environment-climate-change/services/environmental-indicators/air-quality.html)
- [NAPS catalogue](https://open.canada.ca/data/en/dataset/1b36a356-defd-4813-acea-47bc3abd859b)
- [Air Quality Ontario data disclaimer](https://www.airqualityontario.com/science/disclaimer.php)
- [AirNow daily data format](https://files.airnowtech.org/airnow/docs/DailyDataFactSheet.pdf)
- [Ontario AQHI replaced the former Ontario AQI](https://www.airqualityontario.com/press/faq.php)

To complete a genuine old-versus-new source experiment, recover the original raw
files, source IDs and observed coverage; reconstruct the same index version on
both sources over common dates; then apply the same models, availability rules,
and chronological evaluation. The current repository does not contain those inputs.
