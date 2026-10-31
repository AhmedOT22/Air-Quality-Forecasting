"""Validate and explicitly lock the prepared dataset before modelling."""

import argparse
import hashlib
import json
from pathlib import Path
import pandas as pd
from aqi import category, no2_index, ozone_index, pm25_index, so2_index
from forecast import load_data

CONTRACT_VERSION = 1
DEFAULT_INPUT = Path("data/processed/daily_aqi_latest.csv")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    """Production validation must also run under python -O."""
    if not condition:
        raise ValueError(message)


def same_values(actual, expected, message):
    try:
        pd.testing.assert_series_equal(actual, expected, check_names=False)
    except AssertionError as error:
        raise ValueError(message) from error


def validate(path=DEFAULT_INPUT, require_lock=True):
    path = Path(path)
    manifest_path = path.with_suffix(".manifest.json")
    metadata = json.loads(manifest_path.read_text())
    frame = load_data(path)
    require(
        metadata["standard"] == "epa_2024" and frame.aqi_standard.eq("epa_2024").all(),
        "Expected EPA 2024 throughout the snapshot",
    )
    require(
        frame.index[0] == pd.Timestamp("2020-01-01"),
        "Historical data must start in 2020",
    )
    require(
        len(frame) == metadata["calendar_days"], "Calendar count differs from manifest"
    )
    require(
        str(frame.index[0].date()) == metadata["start"]
        and str(frame.index[-1].date()) == metadata["end"],
        "Date bounds differ from manifest",
    )
    components = ["PM25_AQI", "O3_AQI", "NO2_AQI", "SO2_AQI"]
    complete = frame[components].notna().all(axis=1)
    same_values(
        frame.AQI,
        frame[components].max(axis=1).where(complete),
        "AQI must use all four components",
    )
    same_values(
        frame.PM25_AQI, frame.PM25_mean_24h.map(pm25_index), "Incorrect PM2.5 sub-index"
    )
    same_values(
        frame.NO2_AQI, frame.NO2_max_1h.map(no2_index), "Incorrect NO2 sub-index"
    )
    for name, function, fields in [
        ("O3_AQI", ozone_index, ["O3_max_8h_ppb", "O3_max_1h"]),
        ("SO2_AQI", so2_index, ["SO2_max_1h", "SO2_mean_24h"]),
    ]:
        expected = pd.Series(
            [
                function(*values)
                for values in frame[fields].itertuples(index=False, name=None)
            ],
            index=frame.index,
            dtype=float,
        )
        same_values(frame[name], expected, f"Incorrect {name} sub-index")
    same_values(frame.AQI_category, frame.AQI.map(category), "Incorrect AQI category")
    require(
        int(complete.sum()) == metadata["observed_target_days"],
        "Observed count differs from manifest",
    )
    require(
        int((~complete).sum()) == metadata["missing_target_days"],
        "Missing count differs from manifest",
    )
    require(
        pd.to_datetime(frame.aqi_available_after)
        .eq(frame.index + pd.Timedelta(days=1))
        .all(),
        "AQI availability must include the next-day ozone delay",
    )
    hourly_path = path.parent / metadata["hourly_file"]
    require(
        digest(hourly_path) == metadata["hourly_sha256"],
        "Hourly checksum differs from manifest",
    )
    for source in metadata["sources"]:
        require(
            source["url"].startswith("https://") and len(source["sha256"]) == 64,
            "Source provenance needs an HTTPS URL and SHA-256 digest",
        )
    record = {
        "contract_version": CONTRACT_VERSION,
        "input": path.name,
        "input_sha256": digest(path),
        "manifest_sha256": digest(manifest_path),
        "hourly_sha256": digest(hourly_path),
        "standard": metadata["standard"],
        "start": str(frame.index[0].date()),
        "end": str(frame.index[-1].date()),
    }
    if require_lock:
        lock = json.loads(path.with_suffix(".lock.json").read_text())
        if lock != record:
            raise ValueError(
                "ETL snapshot changed; review and explicitly renew its lock before modelling"
            )
    return frame, record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument(
        "--lock", action="store_true", help="Explicitly freeze a validated snapshot"
    )
    args = parser.parse_args()
    _, record = validate(args.input, require_lock=not args.lock)
    if args.lock:
        args.input.with_suffix(".lock.json").write_text(
            json.dumps(record, indent=2) + "\n"
        )
    print(json.dumps(record, indent=2))
