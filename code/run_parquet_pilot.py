#!/usr/bin/env python3
"""Run a frozen correctness/feasibility pilot; no GitHub writes or formal tests.

Run from the repository root:
  .venv/bin/python code/run_parquet_pilot.py --run-id pilot_v1
"""

import argparse
import csv
import hashlib
import io
import json
import math
import os
import platform
import random
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


LAYOUTS = ["random", "station_first", "time_first"]
CANONICAL_KEYS = [("station_id", "ascending"), ("observation_time", "ascending")]
SCHEMA = pa.schema([
    ("station_id", pa.string()),
    ("observation_time", pa.timestamp("us", tz="UTC")),
    ("sst", pa.float64()),
])


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def save_csv(path, rows):
    if not rows:
        raise ValueError(f"Refusing an empty result table: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def logical_digest(table):
    canonical = table.sort_by(CANONICAL_KEYS).combine_chunks()
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, SCHEMA) as writer:
        writer.write_table(canonical)
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


def read_base(manifest):
    stations, times, values = [], [], []
    raw_rows = 0
    if not manifest["complete"] or manifest["errors"]:
        raise ValueError("The data screening snapshot is incomplete")
    for source in manifest["files"]:
        path = Path(source["local_file"])
        if digest(path) != source["sha256"]:
            raise ValueError(f"Input hash mismatch: {path}")
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream)
            if next(reader) != ["station", "time", "WTMP"] or next(reader) != ["", "UTC", "degree_C"]:
                raise ValueError(f"Unexpected columns or units: {path}")
            for station, moment, text_value in reader:
                raw_rows += 1
                value = float(text_value)
                if not math.isfinite(value) or value == -9999999.0:
                    continue
                if station != source["station_id"]:
                    raise ValueError(f"Unexpected station: {path}")
                stations.append(station)
                times.append(timestamp(moment))
                values.append(value)
    if raw_rows != manifest["total_rows"] or len(values) != manifest["total_finite_wtmp_rows"]:
        raise ValueError("Row counts differ from the screened snapshot")
    return pa.Table.from_arrays([
        pa.array(stations, type=SCHEMA.field("station_id").type),
        pa.array(times, type=SCHEMA.field("observation_time").type),
        pa.array(values, type=SCHEMA.field("sst").type),
    ], schema=SCHEMA)


def make_query(query_id, role, kind, station, start, hours):
    end = timestamp(start) + timedelta(hours=hours)
    return {
        "query_id": query_id, "role": role, "kind": kind,
        "station_id": station,
        "start_utc": timestamp(start).isoformat(),
        "end_utc": end.isoformat(), "window_hours": hours,
    }


def build_queries(config, stations):
    pilot, formal = [], []
    for i, case in enumerate(config["pilot_cases"]):
        for kind, key in [("Q1", "q1_window_hours"), ("Q2", "q2_window_hours")]:
            for hours in config[key]:
                pilot.append(make_query(f"pilot_{kind}_{i}_{hours}h", "pilot", kind,
                                        case["station_id"] if kind == "Q1" else None,
                                        case["start_utc"], hours))
    for role, key in [("tuning", "formal_tuning_starts_utc"), ("validation", "formal_validation_starts_utc")]:
        for i, start in enumerate(config[key]):
            for station in stations:
                for hours in config["q1_window_hours"]:
                    formal.append(make_query(f"{role}_Q1_{i}_{station}_{hours}h", role, "Q1", station, start, hours))
            for hours in config["q2_window_hours"]:
                formal.append(make_query(f"{role}_Q2_{i}_{hours}h", role, "Q2", None, start, hours))
    signatures = lambda rows: {(q["kind"], q["station_id"], q["start_utc"], q["end_utc"]) for q in rows}
    if signatures(pilot) & signatures(formal):
        raise ValueError("Pilot and planned formal queries overlap")
    return pilot, formal


def query_sql(query, path=None):
    source = "read_parquet(?)" if path is not None else "reference_data"
    sql = f"SELECT count(*) AS n, avg(sst) AS mean_sst FROM {source} WHERE observation_time >= ? AND observation_time < ?"
    params = ([str(path)] if path is not None else []) + [timestamp(query["start_utc"]), timestamp(query["end_utc"])]
    if query["kind"] == "Q1":
        sql += " AND station_id = ?"
        params.append(query["station_id"])
    return sql, params


def check_answer(actual, expected, config):
    if actual[0] != expected[0]:
        raise AssertionError(f"Count mismatch: {actual} != {expected}")
    if actual[1] is None or expected[1] is None:
        if actual[1] is not expected[1]:
            raise AssertionError(f"NULL aggregate mismatch: {actual} != {expected}")
    elif not math.isclose(actual[1], expected[1], rel_tol=config["relative_tolerance"], abs_tol=config["absolute_tolerance"]):
        raise AssertionError(f"Mean mismatch: {actual} != {expected}")


def extract_groups(path):
    metadata = pq.ParquetFile(path).metadata
    groups = []
    for i in range(metadata.num_row_groups):
        group = metadata.row_group(i)
        columns = {}
        for j in range(group.num_columns):
            column = group.column(j)
            stats = column.statistics
            if not stats or not stats.has_min_max:
                raise AssertionError(f"Missing range statistics: {path}, group {i}")
            low, high = stats.min, stats.max
            columns[column.path_in_schema] = {
                "min": low.isoformat() if isinstance(low, datetime) else low,
                "max": high.isoformat() if isinstance(high, datetime) else high,
                "null_count": stats.null_count,
                "compressed_bytes": column.total_compressed_size,
                "encodings": list(column.encodings),
            }
        groups.append({"row_group": i, "rows": group.num_rows, "columns": columns})
    return groups


def candidate_stats(query, groups):
    selected = []
    lower, upper = timestamp(query["start_utc"]), timestamp(query["end_utc"])
    for group in groups:
        columns = group["columns"]
        bounds = columns["observation_time"]
        if timestamp(bounds["max"]) < lower or timestamp(bounds["min"]) >= upper:
            continue
        if query["kind"] == "Q1":
            station = columns["station_id"]
            if not station["min"] <= query["station_id"] <= station["max"]:
                continue
        selected.append(group)
    needed = ["observation_time", "sst"] + (["station_id"] if query["kind"] == "Q1" else [])
    return {
        "candidate_row_groups_estimate": len(selected),
        "total_row_groups": len(groups),
        "candidate_rows_estimate": sum(g["rows"] for g in selected),
        "candidate_compressed_column_bytes_estimate": sum(g["columns"][c]["compressed_bytes"] for g in selected for c in needed),
        "metric_kind": "metadata_estimate_not_measured_disk_io",
    }


def environment(con):
    details = {
        "python": platform.python_version(), "pyarrow": pa.__version__, "duckdb": duckdb.__version__,
        "system": platform.system(), "kernel": platform.release(), "machine": platform.machine(),
        "reported_logical_cpus": os.cpu_count(),
        "cpu_affinity_count": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "duckdb_settings": dict(con.execute("SELECT name,value FROM duckdb_settings() WHERE name IN ('threads','TimeZone','enable_external_file_cache','memory_limit')").fetchall()),
    }
    for name in ["memory.max", "cpu.max"]:
        path = Path("/sys/fs/cgroup") / name
        if path.exists():
            details["cgroup_" + name] = path.read_text().strip()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        details["cpu_model"] = next((line.split(":", 1)[1].strip() for line in cpuinfo.read_text().splitlines() if line.startswith("model name")), None)
    return details


def run(config_path, run_id):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    out = Path("results") / run_id
    data_dir = Path("data/parquet") / run_id
    if out.exists() or data_dir.exists():
        raise ValueError("Run ID already exists; choose a new ID to preserve earlier evidence")
    out.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    status_path = out / "run_status.json"
    save_json(status_path, {"status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat()})
    try:
        manifest_path = Path(config["data_manifest"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        queries, formal = build_queries(config, manifest["requested_stations"])
        con = duckdb.connect()
        con.execute(f"SET threads={int(config['threads'])}")
        con.execute("SET TimeZone='UTC'")
        if not pa.Codec.is_available(config["writer"]["compression"]):
            raise RuntimeError("Configured compression codec is unavailable")
        protocol = {
            "run_id": run_id, "config": config, "config_sha256": digest(config_path),
            "script_sha256": digest(Path(__file__)), "source_manifest_sha256": digest(manifest_path),
            "experiment_protocol_sha256": digest(Path("report/04_experiment_protocol.md")),
            "environment": environment(con), "cache_regime": "warm; includes engine and OS caches; no cold-cache claim",
            "frozen_before_first_timing": True,
        }
        save_json(out / "protocol.json", protocol)
        save_json(out / "pilot_queries.json", queries)
        save_json(out / "planned_formal_queries_NOT_RUN.json", formal)
        base = read_base(manifest)
        base_digest = logical_digest(base)
        con.register("reference_data", base)
        duplicate_keys = con.execute("SELECT count(*) FROM (SELECT station_id,observation_time FROM reference_data GROUP BY ALL HAVING count(*)>1)").fetchone()[0]
        if duplicate_keys:
            raise AssertionError("Unexpected duplicate keys in canonical input")
        layouts, groups_by_layout = {}, {}
        for layout in LAYOUTS:
            start = time.perf_counter_ns()
            if layout == "random":
                indices = list(range(base.num_rows))
                random.Random(config["random_seed"]).shuffle(indices)
                table = base.take(pa.array(indices, type=pa.uint32()))
            else:
                keys = CANONICAL_KEYS if layout == "station_first" else list(reversed(CANONICAL_KEYS))
                table = base.sort_by(keys)
            table = table.combine_chunks()
            sorted_at = time.perf_counter_ns()
            path = data_dir / (layout + ".parquet")
            pq.write_table(table, path, **config["writer"])
            written_at = time.perf_counter_ns()
            restored = pq.ParquetFile(path).read().combine_chunks()
            if restored.schema != SCHEMA or restored.num_rows != base.num_rows or logical_digest(restored) != base_digest:
                raise AssertionError(f"Layout logical contents differ: {layout}")
            if layout != "random" and not restored.equals(restored.sort_by(keys)):
                raise AssertionError(f"Layout rows are not really sorted: {layout}")
            groups = extract_groups(path)
            expected_groups = math.ceil(base.num_rows / config["writer"]["row_group_size"])
            if len(groups) != expected_groups or len(groups) < 2:
                raise AssertionError(f"Unexpected row-group count: {layout}")
            for i, group in enumerate(groups):
                expected_rows = min(config["writer"]["row_group_size"], base.num_rows - i * config["writer"]["row_group_size"])
                if group["rows"] != expected_rows:
                    raise AssertionError(f"Unexpected row-group boundary: {layout}/{i}")
            layouts[layout] = {
                "path": path.as_posix(), "rows": restored.num_rows, "row_groups": len(groups),
                "file_bytes": path.stat().st_size, "file_sha256": digest(path), "logical_sha256": base_digest,
                "ordering_ms": (sorted_at - start) / 1e6,
                "writing_ms": (written_at - sorted_at) / 1e6,
            }
            groups_by_layout[layout] = groups
            print(f"{layout}: {restored.num_rows} rows, {len(groups)} row groups, {path.stat().st_size} bytes", flush=True)
        save_json(out / "layout_manifest.json", layouts)
        save_json(out / "row_group_metadata.json", groups_by_layout)
        references, checks, plans, candidates = {}, [], {}, []
        for query in queries:
            sql, params = query_sql(query)
            answer = con.execute(sql, params).fetchone()
            references[query["query_id"]] = answer
            for layout in LAYOUTS:
                sql, params = query_sql(query, layouts[layout]["path"])
                actual = con.execute(sql, params).fetchone()
                check_answer(actual, answer, config)
                checks.append({"query_id": query["query_id"], "layout": layout, "count": actual[0], "mean_sst": actual[1], "matches_reference": True})
                plans[query["query_id"] + "/" + layout] = con.execute("EXPLAIN " + sql, params).fetchall()
                estimate = candidate_stats(query, groups_by_layout[layout])
                if actual[0] > estimate["candidate_rows_estimate"]:
                    raise AssertionError("Metadata candidate estimate excludes matching rows")
                candidates.append({"query_id": query["query_id"], "layout": layout, **estimate})
        save_json(out / "correctness.json", {"base_rows": base.num_rows, "duplicate_keys": duplicate_keys, "base_logical_sha256": base_digest, "checks": checks})
        save_json(out / "query_plans.json", plans)
        save_csv(out / "candidate_row_groups.csv", candidates)
        measurements = []
        rng = random.Random(config["random_seed"])
        for phase, rounds in [("warmup", config["warmup_repetitions"]), ("measured", config["measured_repetitions"])]:
            for repetition in range(rounds):
                query_order = list(queries)
                rng.shuffle(query_order)
                for query_position, query in enumerate(query_order):
                    offset = (repetition + query_position) % len(LAYOUTS)
                    order = LAYOUTS[offset:] + LAYOUTS[:offset]
                    for layout_position, layout in enumerate(order):
                        sql, params = query_sql(query, layouts[layout]["path"])
                        start = time.perf_counter_ns()
                        actual = con.execute(sql, params).fetchone()
                        elapsed_ms = (time.perf_counter_ns() - start) / 1e6
                        check_answer(actual, references[query["query_id"]], config)
                        measurements.append({
                            "phase": phase, "repetition": repetition + 1, "query_position": query_position,
                            "layout_position": layout_position, "query_id": query["query_id"], "kind": query["kind"],
                            "station_id": query["station_id"], "window_hours": query["window_hours"], "layout": layout,
                            "elapsed_ms": elapsed_ms, "count": actual[0], "mean_sst": actual[1],
                            "selectivity": actual[0] / base.num_rows,
                        })
        save_csv(out / "measurements.csv", measurements)
        grouped = defaultdict(list)
        for row in measurements:
            if row["phase"] == "measured":
                grouped[(row["query_id"], row["layout"])].append(row["elapsed_ms"])
        summary = []
        by_id = {query["query_id"]: query for query in queries}
        for (query_id, layout), values in sorted(grouped.items()):
            q = by_id[query_id]
            quartiles = statistics.quantiles(values, n=4, method="inclusive")
            summary.append({
                "query_id": query_id, "kind": q["kind"], "station_id": q["station_id"], "window_hours": q["window_hours"],
                "layout": layout, "repetitions": len(values), "mean_ms": statistics.mean(values),
                "median_ms": statistics.median(values), "min_ms": min(values), "max_ms": max(values),
                "q25_ms": quartiles[0], "q75_ms": quartiles[2], "count": references[query_id][0],
            })
        save_csv(out / "query_summary.csv", summary)
        measured = sum(row["phase"] == "measured" for row in measurements)
        warmups = len(measurements) - measured
        if measured != len(queries) * len(LAYOUTS) * config["measured_repetitions"]:
            raise AssertionError("Missing timed measurements")
        status = {
            "status": "passed", "completed_at_utc": datetime.now(timezone.utc).isoformat(), "base_rows": base.num_rows,
            "pilot_queries": len(queries), "planned_formal_queries_not_run": len(formal),
            "correctness_checks": len(checks), "measured_queries": measured, "extra_warmup_queries": warmups,
            "scope": "Pilot only; no statistical significance or universal ranking claim",
        }
        save_json(status_path, status)
        print(json.dumps(status, ensure_ascii=False), flush=True)
        con.close()
    except Exception as error:
        save_json(status_path, {"status": "failed", "error": str(error), "at_utc": datetime.now(timezone.utc).isoformat()})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/pilot_v1.json"))
    parser.add_argument("--run-id", default="pilot_v1")
    args = parser.parse_args()
    if not args.run_id or not all(c.isalnum() or c in "_-" for c in args.run_id):
        parser.error("Use letters, digits, underscores or hyphens for run IDs")
    run(args.config, args.run_id)
