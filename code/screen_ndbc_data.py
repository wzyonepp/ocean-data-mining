#!/usr/bin/env python3
"""Download and profile a fixed NDBC subset from NOAA ERDDAP (stdlib only).

This checks data suitability; it does not benchmark Parquet queries.
Run from the repository root: python code/screen_ndbc_data.py
"""

import argparse
import csv
import hashlib
import io
import json
import math
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_BASE = "https://upwell.pfeg.noaa.gov/erddap"
DEFAULT_FALLBACK = "https://coastwatch.pfeg.noaa.gov/erddap"
DEFAULT_STATIONS = ["41001", "41002", "41004", "41008", "41009", "41010", "41013", "41025"]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def fetch_cached(url, path, fallback_url=None):
    """Keep downloaded responses and their acquisition time; verify cache hashes."""
    urls = list(dict.fromkeys([url] + ([fallback_url] if fallback_url else [])))
    sidecar = path.with_suffix(path.suffix + ".metadata.json")
    if path.exists() and sidecar.exists():
        raw = path.read_bytes()
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        if metadata["url"] not in urls or hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
            raise ValueError(f"Cache URL/hash mismatch: {path}; use a new output directory")
        return raw, metadata
    failures = []
    for candidate in urls:
        try:
            request = urllib.request.Request(candidate, headers={"User-Agent": "MarineDataMiningCourse/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
            break
        except (urllib.error.URLError, TimeoutError) as error:
            failures.append({"url": candidate, "error": str(error), "at_utc": utc_now()})
            if candidate == urls[-1]:
                raise
            print(f"Primary endpoint failed ({error}); trying NOAA fallback", file=sys.stderr, flush=True)
    metadata = {
        "url": candidate,
        "retrieved_at_utc": utc_now(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "failed_requests": failures,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    sidecar.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return raw, metadata


def profile_station_year(base, fallback, station, year, output_dir):
    start = f"{year}-01-01T00:00:00Z"
    end = f"{year + 1}-01-01T00:00:00Z"
    query = f'station,time,WTMP&station="{station}"&time>={start}&time<{end}'
    url = base + "/tabledap/cwwcNDBCMet.csv?" + urllib.parse.quote(query, safe="=&,:")
    fallback_url = fallback + "/tabledap/cwwcNDBCMet.csv?" + urllib.parse.quote(query, safe="=&,:")
    path = output_dir / f"{station}_{year}.csv"
    raw, acquisition = fetch_cached(url, path, fallback_url)
    reader = csv.reader(io.StringIO(raw.decode("utf-8")))
    if next(reader) != ["station", "time", "WTMP"]:
        raise ValueError(f"Unexpected CSV columns: {url}")
    if next(reader) != ["", "UTC", "degree_C"]:
        raise ValueError(f"Unexpected CSV units: {url}")
    lower = datetime(year, 1, 1, tzinfo=timezone.utc)
    upper = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    timestamps = []
    valid_timestamps = []
    values = []
    values_by_time = {}
    months = Counter()
    for row in reader:
        if not row:
            continue
        if len(row) != 3 or row[0] != station:
            raise ValueError(f"Unexpected station/row: {row}")
        moment = datetime.fromisoformat(row[1].replace("Z", "+00:00"))
        if moment.tzinfo is None or not lower <= moment < upper:
            raise ValueError(f"Out-of-range timestamp: {row}")
        value = float(row[2])
        timestamps.append(moment)
        # ERDDAP CSV normally renders missing values as NaN. Its metadata also
        # defines -9999999 as the missing sentinel; do not use NDBC text codes.
        if math.isfinite(value) and value != -9999999.0:
            valid_timestamps.append(moment)
            values.append(value)
            months[moment.strftime("%Y-%m")] += 1
            values_by_time.setdefault(moment, set()).add(value)
    unique_times = sorted(set(timestamps))
    steps = [(b - a).total_seconds() for a, b in zip(unique_times, unique_times[1:])]
    return {
        "station_id": station,
        "year": year,
        **acquisition,
        "local_file": path.as_posix(),
        "rows": len(timestamps),
        "finite_wtmp_rows": len(values),
        "missing_wtmp_rows": len(timestamps) - len(values),
        "duplicate_station_time_rows": len(timestamps) - len(unique_times),
        "conflicting_finite_values_at_same_time": sum(len(v) > 1 for v in values_by_time.values()),
        "first_timestamp_utc": min(timestamps).isoformat() if timestamps else None,
        "last_timestamp_utc": max(timestamps).isoformat() if timestamps else None,
        "first_finite_wtmp_timestamp_utc": min(valid_timestamps).isoformat() if values else None,
        "last_finite_wtmp_timestamp_utc": max(valid_timestamps).isoformat() if values else None,
        "wtmp_min_c": min(values) if values else None,
        "wtmp_max_c": max(values) if values else None,
        "median_timestamp_step_seconds": statistics.median(steps) if steps else None,
        "max_timestamp_gap_seconds": max(steps) if steps else None,
        "finite_wtmp_rows_by_month": dict(sorted(months.items())),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--fallback-base-url", default=DEFAULT_FALLBACK)
    parser.add_argument("--stations", nargs="+", default=DEFAULT_STATIONS)
    parser.add_argument("--years", type=int, nargs="+", default=[2023, 2024])
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--manifest", type=Path, default=Path("results/data_screening_manifest.json"))
    args = parser.parse_args()
    args.stations = sorted(set(args.stations))
    args.years = sorted(set(args.years))
    if not all(len(s) == 5 and s.isalnum() for s in args.stations):
        parser.error("Station IDs must have five alphanumeric characters")
    if not all(1970 <= year < datetime.now(timezone.utc).year for year in args.years):
        parser.error("Select complete historical years since 1970")
    base = args.base_url.rstrip("/")
    fallback = args.fallback_base_url.rstrip("/")
    metadata_url = base + "/info/cwwcNDBCMet/index.csv"
    metadata_raw, metadata_acquisition = fetch_cached(metadata_url, args.output_dir / "dataset_metadata.csv")
    metadata_rows = list(csv.DictReader(io.StringIO(metadata_raw.decode("utf-8"))))
    attributes = {
        (row["Variable Name"], row["Attribute Name"]): row["Value"]
        for row in metadata_rows if row["Row Type"] == "attribute"
    }
    if attributes[("WTMP", "units")] != "degree_C":
        raise ValueError("Unexpected water-temperature unit in dataset metadata")
    results = []
    errors = []
    jobs = [(station, year) for station in args.stations for year in args.years]
    # Limit server load; no more than two concurrent subset requests.
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = {
            executor.submit(profile_station_year, base, fallback, station, year, args.output_dir): (station, year)
            for station, year in jobs
        }
        for future in as_completed(pending):
            station, year = pending[future]
            try:
                result = future.result()
                results.append(result)
                print(f"{station} {year}: rows={result['rows']}, finite_wtmp={result['finite_wtmp_rows']}", flush=True)
            except Exception as error:
                errors.append({"station_id": station, "year": year, "error": str(error)})
                print(f"{station} {year}: ERROR {error}", file=sys.stderr, flush=True)
    results.sort(key=lambda row: (row["station_id"], row["year"]))
    manifest = {
        "screened_at_utc": utc_now(),
        "purpose": "Data-source screening only; no Parquet performance experiments run",
        "python_version": sys.version.split()[0],
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "dataset_id": "cwwcNDBCMet",
        "primary_base_url": base,
        "fallback_base_url": fallback,
        "metadata_snapshot": metadata_acquisition,
        "metadata_facts": {
            "institution": attributes[("NC_GLOBAL", "institution")],
            "wtmp_standard_name": attributes[("WTMP", "standard_name")],
            "wtmp_units": attributes[("WTMP", "units")],
            "wtmp_missing_value": attributes[("WTMP", "missing_value")],
        },
        "requested_stations": args.stations,
        "requested_years": args.years,
        "expected_files": len(jobs),
        "completed_files": len(results),
        "complete": len(results) == len(jobs) and not errors,
        "total_rows": sum(r["rows"] for r in results),
        "total_finite_wtmp_rows": sum(r["finite_wtmp_rows"] for r in results),
        "total_missing_wtmp_rows": sum(r["missing_wtmp_rows"] for r in results),
        "total_duplicate_station_time_rows": sum(r["duplicate_station_time_rows"] for r in results),
        "total_csv_bytes": sum(r["bytes"] for r in results),
        "files": results,
        "errors": errors,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Saved {args.manifest}: {len(results)}/{len(jobs)} files, {manifest['total_rows']} rows", flush=True)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
