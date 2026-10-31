# Sources, station identity, and preparation

## Official observations

### Pollution

Use the [NAPS ECCC catalogue](https://data-donnees.az.ec.gc.ca/data/air/monitor/national-air-pollution-surveillance-naps-program/).
The Government of Canada describes NAPS observations as quality-assured submissions
from provincial, territorial, and regional monitoring networks. These are revised
historical observations, not an untouched real-time feed.

Files for each year 2020–2024 are under:

```text
Data-Donnees/{year}/ContinuousData-DonneesContinu/HourlyData-DonneesHoraires/PM25_{year}.csv
```

The downloader uses the catalogue's current `/api/file?path=...` download endpoint.
It reads the real bilingual header after the file preamble; no fixed skip-row count
or legacy local file layout is assumed. Source files explicitly specify PM2.5 in
µg/m³, hour-ending local standard time, valid zeros, and `-999` for missing data.

Station `060430` is **Toronto West**, 125 Resources Road, approximately
43.70944°N, 79.54350°W. The station record starts in 2000 and has no end date in
the retrieved metadata. The prepared period uses one stable station ID and
coordinates; it does not join the relocated Downtown sites or average Toronto sites.
The default choice provides a consistent site with high hourly completeness near
a long-running weather station. It was not selected by model accuracy.

The metadata lists method `184` in 2020–2021, `184` and `636` in 2022, and `636`
in 2023–2024. In 2022, complementary valid hours from the two methods are combined
at the station/date/hour level. Any overlapping valid readings are an error,
even if their values agree. Duplicate station/method/day rows also fail validation.
Raw method IDs are retained in cached source files and summarized by year in the manifest.
This handles the file structure; it does not establish instrument-method equivalence.

### Weather

Use [MSC GeoMet hourly climate observations](https://api.weather.gc.ca/collections/climate-hourly?f=html),
climate identifier `6158731`, **Toronto Intl A** (Pearson), station ID `51459`.
The station is approximately 43.67667°N, 79.63056°W, about 7.9 km from the pollution site.
Both station records and all selected weather flags are cached and checksummed.

Queries specify `CLIMATE_IDENTIFIER`, `LOCAL_YEAR`, selected properties and a 10,000
record limit. The collection's temporal filtering uses local dates; using UTC-shifted
`datetime` bounds would wrongly omit the first five local hours and include hours
from the following year. Preparation verifies the returned local years and refuses
responses with a `next` page link. Annual Toronto files contain fewer than 10,000 observations.

Selected hourly variables:

| Prepared daily field | ECCC field | Unit |
| --- | --- | --- |
| `temperature_c` | `TEMP` | °C |
| `humidity_pct` | `RELATIVE_HUMIDITY` | % |
| `wind_speed_kmh` | `WIND_SPEED` | km/h |
| `pressure_kpa` | `STATION_PRESSURE` | kPa |

Daily weather predictors are means of unflagged, finite observations with at least
18 hours per variable. Humidity outside 0–100%, negative wind speeds, and nonpositive
pressure are excluded. Precipitation is not silently treated as zero: the tested
hourly endpoint lacks usable precipitation for this configuration, so it is omitted.

## Daily quality contract

The time basis is **fixed UTC−5 local standard time**, with no DST adjustment.
Pollution `H01`–`H24` represents the completed reporting day's 24 hour-ending
intervals. Weather uses that day's local-standard timestamps `00:00`–`23:00`.
The weather means are summaries of hourly meteorological observations, not a claim
that each timestamp is an interval-end pollutant measurement.

1. Preserve station identity and calendar dates.
2. Treat NAPS `-999` as missing; retain zero. Exclude and count other negative concentrations.
3. Combine complementary method hours; never double-count hours or average conflicting instruments.
4. Require at least **18 valid pollution hours** to form a daily mean. This is the
   project's explicit 75% coverage rule, not a claim that the mean is an official AQI.
5. Retain all calendar dates, including wholly missing/insufficient days.
6. Join weather by local-standard date with a one-to-one validation.
7. Never fill missing target concentrations. Training-only imputation may fill
   weather predictors, with missingness indicators, during model fitting.

Observed snapshot:

| Year | Calendar days | Qualified PM2.5 days | Missing target days |
| --- | ---: | ---: | ---: |
| 2020 | 366 | 358 | 8 |
| 2021 | 365 | 360 | 5 |
| 2022 | 365 | 360 | 5 |
| 2023 | 365 | 359 | 6 |
| 2024 | 366 | 364 | 2 |
| Total | 1,827 | 1,801 | 26 |

Each of the four weather features has 1,826 qualifying daily means. The coverage
counts stay in the prepared CSV. No clipping of high PM2.5 episodes is performed.

## Provenance and reproduction

`daily_pm25.manifest.json` records the exact source URLs, SHA-256 digests, retrieval
timestamps, station metadata, annual methods/coverage, time convention, and prepared
CSV digest. Raw files and their source sidecars are ignored by Git. The prepared
snapshot and manifest are tracked for offline reproducibility.

A cached file whose digest or recorded URL changes is rejected. `--refresh`
explicitly requests new provider versions. Old published versions may be replaced
by ECCC at the same URL; the committed daily snapshot freezes the benchmark input,
but reproducing its raw bytes later is not guaranteed by the provider.

The default supported configuration deliberately fixes this EST station pair.
Another station or timezone requires a reviewed configuration and metadata checks,
rather than changing an ID while retaining Toronto's time assumptions.

References:

- [NAPS data catalogue record and licence](https://open.canada.ca/data/en/dataset/1b36a356-defd-4813-acea-47bc3abd859b)
- [NAPS monitoring and data validation](https://www.canada.ca/en/environment-climate-change/services/environmental-indicators/air-quality.html)
- [MSC historical observations API documentation](https://eccc-msc.github.io/open-data/msc-data/climate_obs/readme_climateobs-geomet_en/)
- [GeoMet query documentation](https://eccc-msc.github.io/open-data/msc-geomet/ogc_api_en/)

The target is concentration, not the archived homemade AQI. The original raw-file
provenance remains unverified and is not used for these results.
