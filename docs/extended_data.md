# Concatenated observations from 2020 onward

`python extend_data.py` downloads Toronto West Ontario CSV exports for all four
pollutants, starting on January 1, 2020 and ending today in fixed EST. The export
endpoint supports 2026 observations even though the historical search form currently
limits its date picker to 2025. A requested NAPS 2025 PM2.5 file returned 404 during
this acquisition; the available NAPS archive used here remains 2020–2024.

## Published datasets

- `data/processed/hourly_pollution_2020_latest.csv.gz`: complete hourly calendar,
  four concentrations, chosen source and verification status. Read directly with
  `pd.read_csv(path, parse_dates=['timestamp_est'])`.
- `data/processed/daily_aqi_latest.csv`: EPA 2024 AQI, components, categories,
  concentrations, coverage, daily weather and source labels. EPA 2018 remains a
  comparison column. Only completed EST days are included.
- `data/processed/daily_aqi_latest.manifest.json`: source URLs, retrieval times,
  SHA-256 digests, duplicate-date quarantine, overlap diagnostics and annual coverage.

Snapshot acquired October 31, 2026:

| Year | Calendar days in daily dataset | Complete AQI days |
| --- | ---: | ---: |
| 2020 | 366 | 345 |
| 2021 | 365 | 356 |
| 2022 | 365 | 346 |
| 2023 | 365 | 308 |
| 2024 | 366 | 355 |
| 2025 | 365 | 356 |
| 2026 through October 30 | 303 | 292 |
| Total | 2,495 | 2,358 |

The hourly snapshot retains available October 31 observations through the interval
starting 09:00 EST (ending 10:00). Incomplete current-day readings are not represented
as a completed daily target. The same availability delay applies when forecasting.
The following morning's observations can qualify October 30 ozone windows without
making October 30 AQI an eligible input earlier than its documented availability.

## Concatenation rules

1. Never include observations earlier than 2020.
2. Keep NAPS readings and their missing values through December 31, 2024. Do not
   overwrite historical gaps using another source or average overlapping readings.
3. Append Ontario readings from January 1, 2025 onward. Ontario station `35125`
   maps to NAPS `060430`, Toronto West, 125 Resources Road, matching coordinates.
4. Ontario CSVs provide `Station ID`, `Pollutant`, `Date`, `H01`–`H24`. Their footer
   explicitly labels the export EST, unlike the site's daylight-saving web display.
   Align H01–H24 with the existing NAPS hour-ending interval convention. The pipeline
   stores interval starts on a fixed UTC−5 calendar, without a DST conversion.
5. Parse variable-length current-day rows and trailing empty CSV fields. Retain zeros;
   exclude Ontario `9999`, negative readings including `-999`, and blanks.
6. Quarantine every Ontario row with a repeated date. The downloaded export repeats
   dates and omits the following dates, with overlapping conflicting measurements.
   Do not infer corrected dates or merge conflicting hours. Original bytes remain cached.
7. Preserve every hourly/daily slot. Apply the existing coverage and EPA 2024 formulas;
   never impute a target or compute AQI from fewer than four components.
8. Extend Pearson weather from the same ECCC hourly endpoint through 2025–2026,
   retaining the existing flags, coverage and training-only imputation policy.

Repeated Ontario dates were 2020-06-22, 2022-04-21, 2022-11-03, 2023-09-12,
2024-10-25, 2026-05-08 and 2026-09-05, for all four pollutants. Only the two
2026 repeated dates affect the appended period; the missing following dates remain
empty too. NAPS retains precedence over all earlier conflicts.

December 31, 2024 now has next-morning Ontario ozone support, so it can produce an
AQI where the isolated NAPS archive could not. Its `aqi_input_source` is explicitly
`NAPS|Ontario`. Other days use their indicated source. Ontario-containing AQI values
are marked `includes_unverified_observations`; final verification has not been
established. These observations are not claimed to be finalized NAPS-quality data.
Ontario's disclaimer says unverified readings should not be used in published
documents; the experimental extension is distinguished from the quality-assured
historical benchmark.

## Overlap and reproducibility

Before appending, compare available valid hours over 2020–2024. The snapshot has:

| Pollutant | Comparable hours | Mean absolute concentration difference |
| --- | ---: | ---: |
| PM2.5 | 43,201 | 0.000394 µg/m³ |
| O3 | 43,069 | 0 ppb |
| NO2 | 42,960 | 0.249669 ppb |
| SO2 | 41,717 | 0.004813 ppb |

These diagnostics support alignment, not guaranteed equivalence or a source-only
accuracy improvement. NAPS gas values and Ontario values differ in numeric precision.
No correction or rounding is applied to conceal those differences.

Raw files and sidecars are cached under `data/raw/ontario/`; requested end dates
appear in their filenames. Repeat with an explicit `--end-date 2026-10-31` to reuse
this cache. `--refresh` deliberately downloads revised Ontario exports and extension
weather; rerun downstream work afterward. The compressed hourly snapshot has a fixed
gzip timestamp for stable content checksums.

The frozen `daily_aqi.csv`, executed notebook and `reports/aqi/2023/` and `/2024/`
remain the existing historical benchmark. The new `daily_aqi_latest.csv` is the
extended input for subsequent forward forecasting. This acquisition does not
silently change the sample used to calculate previously published model scores.

## Sources

- [Ontario CSV search](https://www.airqualityontario.com/history/index.php)
- [Toronto West station](https://www.airqualityontario.com/history/station.php?stationid=35125)
- [Ontario disclaimer](https://www.airqualityontario.com/science/disclaimer.php)
- [NAPS archive](https://data-donnees.az.ec.gc.ca/data/air/monitor/national-air-pollution-surveillance-naps-program/)
- [ECCC climate observations API](https://eccc-msc.github.io/open-data/msc-data/climate_obs/readme_climateobs-geomet_en/)
