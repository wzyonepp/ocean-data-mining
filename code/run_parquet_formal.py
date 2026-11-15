#!/usr/bin/env python3
"""Execute preregistered queries, freeze tuning decisions, then time validation.

This reuses immutable, hash-checked pilot Parquet files. It never writes GitHub.
Run from the repository root with the pinned environment.
"""

import argparse
import json
import random
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

import run_parquet_pilot as common


def timestamp_now():
    return datetime.now(timezone.utc).isoformat()


def mean_costs(rows):
    grouped = defaultdict(list)
    for row in rows:
        if row["phase"] == "measured":
            grouped[(row["layout"], row["kind"])].append(row["elapsed_ms"])
    return {layout: {kind: statistics.mean(grouped[(layout, kind)]) for kind in ["Q1", "Q2"]}
            for layout in common.LAYOUTS}


def fit_decisions(tuning_rows, config, pilot_config):
    costs = mean_costs(tuning_rows)
    decisions = []
    for p in pilot_config["formal_mixture_q1_proportions"]:
        weighted = {layout: p * costs[layout]["Q1"] + (1 - p) * costs[layout]["Q2"]
                    for layout in config["candidate_layouts"]}
        minimum = min(weighted.values())
        winners = [layout for layout, value in weighted.items() if value == minimum]
        chosen = config["tie_breaker"] if config["tie_breaker"] in winners else winners[0]
        decisions.append({"q1_proportion": p, "chosen_layout": chosen, "tuning_costs_ms": weighted})
    return {"costs_by_query_type_ms": costs, "decisions": decisions,
            "metric": config["selection_metric"], "uses_validation_timings": False}


def measure_role(role, queries, con, layouts, answers, config, counter):
    rows = []
    rng = random.Random(config["random_seed"])
    for phase, rounds in [("warmup", config["warmup_repetitions"]), ("measured", config["measured_repetitions"])]:
        for repetition in range(rounds):
            shuffled = list(queries)
            rng.shuffle(shuffled)
            for position, query in enumerate(shuffled):
                offset = (repetition + position) % len(common.LAYOUTS)
                order = common.LAYOUTS[offset:] + common.LAYOUTS[:offset]
                for layout_position, layout in enumerate(order):
                    sql, params = common.query_sql(query, layouts[layout]["path"])
                    started_ns = time.perf_counter_ns()
                    actual = con.execute(sql, params).fetchone()
                    elapsed_ms = (time.perf_counter_ns() - started_ns) / 1e6
                    common.check_answer(actual, answers[query["query_id"]], config)
                    counter[0] += 1
                    rows.append({
                        "execution_order": counter[0], "role": role, "phase": phase,
                        "repetition": repetition + 1, "query_position": position,
                        "layout_position": layout_position, "query_id": query["query_id"],
                        "kind": query["kind"], "station_id": query["station_id"],
                        "start_utc": query["start_utc"], "window_hours": query["window_hours"],
                        "layout": layout, "elapsed_ms": elapsed_ms,
                        "count": actual[0], "mean_sst": actual[1], "start_monotonic_ns": started_ns,
                    })
    return rows


def summarize(rows):
    grouped = defaultdict(list)
    for row in rows:
        if row["phase"] == "measured":
            grouped[(row["query_id"], row["layout"])].append(row)
    output = []
    for (query_id, layout), records in sorted(grouped.items()):
        times = [record["elapsed_ms"] for record in records]
        first = records[0]
        quartiles = statistics.quantiles(times, n=4, method="inclusive")
        output.append({
            **{key: first[key] for key in ["role", "kind", "station_id", "start_utc", "window_hours", "count"]},
            "query_id": query_id, "layout": layout, "repetitions": len(times),
            "mean_ms": statistics.mean(times), "median_ms": statistics.median(times),
            "min_ms": min(times), "max_ms": max(times), "q25_ms": quartiles[0], "q75_ms": quartiles[2],
        })
    return output


def diagnose_groups(queries, layouts, all_groups, answers, config):
    """Count matching rows by reading candidate groups, outside benchmark timers."""
    details, summary = [], []
    files = {layout: pq.ParquetFile(layouts[layout]["path"]) for layout in config["diagnostic_layouts"]}
    for query in queries:
        lower, upper = common.timestamp(query["start_utc"]), common.timestamp(query["end_utc"])
        for layout, file in files.items():
            candidates = []
            for group in all_groups[layout]:
                columns = group["columns"]
                bounds = columns["observation_time"]
                if common.timestamp(bounds["max"]) < lower or common.timestamp(bounds["min"]) >= upper:
                    continue
                station = columns["station_id"]
                if query["kind"] == "Q1" and not station["min"] <= query["station_id"] <= station["max"]:
                    continue
                table = file.read_row_group(group["row_group"], columns=["station_id", "observation_time"], use_threads=False)
                dtype = table.schema.field("observation_time").type
                mask = pc.and_(pc.greater_equal(table["observation_time"], pa.scalar(lower, type=dtype)),
                               pc.less(table["observation_time"], pa.scalar(upper, type=dtype)))
                if query["kind"] == "Q1":
                    mask = pc.and_(mask, pc.equal(table["station_id"], query["station_id"]))
                matches = pc.sum(pc.cast(mask, pa.int64())).as_py()
                row = {"query_id": query["query_id"], "role": query["role"], "kind": query["kind"],
                       "window_hours": query["window_hours"], "layout": layout,
                       "row_group": group["row_group"], "matching_rows": matches,
                       "station_min": station["min"], "station_max": station["max"],
                       "crosses_station_boundary": station["min"] != station["max"]}
                candidates.append(row)
                details.append(row)
            if sum(row["matching_rows"] for row in candidates) != answers[query["query_id"]][0]:
                raise AssertionError("Candidate-group inspection lost matching rows")
            summary.append({
                "query_id": query["query_id"], "role": query["role"], "kind": query["kind"],
                "window_hours": query["window_hours"], "layout": layout,
                "candidate_groups": len(candidates),
                "groups_with_matching_rows": sum(row["matching_rows"] > 0 for row in candidates),
                "false_positive_groups": sum(row["matching_rows"] == 0 for row in candidates),
                "false_positive_boundary_groups": sum(row["matching_rows"] == 0 and row["crosses_station_boundary"] for row in candidates),
                "matching_rows": answers[query["query_id"]][0],
                "metric_kind": "independent_Arrow_inspection_not_DuckDB_io_trace",
            })
    return details, summary


def run(config_path, run_id):
    config = json.loads(config_path.read_text())
    pilot_config_path = Path(config["pilot_config"])
    pilot_config = json.loads(pilot_config_path.read_text())
    pilot_dir = Path(config["pilot_results"])
    out = Path("results") / run_id
    if out.exists():
        raise ValueError("Choose a fresh run ID; existing results are never overwritten")
    out.mkdir(parents=True)
    status = out / "run_status.json"
    common.save_json(status, {"status": "running", "started_at_utc": timestamp_now()})
    try:
        source_path = Path(pilot_config["data_manifest"])
        manifest = json.loads(source_path.read_text())
        frozen_queries_path = Path(config["preregistered_queries"])
        queries = json.loads(frozen_queries_path.read_text())
        _, regenerated = common.build_queries(pilot_config, manifest["requested_stations"])
        if queries != regenerated:
            raise AssertionError("Formal queries changed from their preregistered definition")
        roles = {role: [q for q in queries if q["role"] == role] for role in ["tuning", "validation"]}
        if any(len(values) != config["expected_queries_per_role"] for values in roles.values()):
            raise AssertionError("Unexpected tuning/validation split")
        layouts_path = pilot_dir / "layout_manifest.json"
        layouts = json.loads(layouts_path.read_text())
        pilot_protocol = json.loads((pilot_dir / "protocol.json").read_text())
        if common.digest(pilot_config_path) != pilot_protocol["config_sha256"]:
            raise AssertionError("Pilot configuration has changed")
        if common.digest(source_path) != pilot_protocol["source_manifest_sha256"]:
            raise AssertionError("Source data manifest has changed")
        con = duckdb.connect()
        con.execute(f"SET threads={int(pilot_config['threads'])}")
        con.execute("SET TimeZone='UTC'")
        env = common.environment(con)
        for package in ["python", "pyarrow", "duckdb"]:
            if env[package] != pilot_protocol["environment"][package]:
                raise AssertionError(f"Version changed since pilot: {package}")
        protocol = {
            "run_id": run_id, "created_at_utc": timestamp_now(), "config": config,
            "pilot_config": pilot_config, "environment": env,
            "config_sha256": common.digest(config_path), "script_sha256": common.digest(Path(__file__)),
            "helper_script_sha256": common.digest(Path(common.__file__)),
            "source_manifest_sha256": common.digest(source_path),
            "layout_manifest_sha256": common.digest(layouts_path),
            "query_file_sha256": common.digest(frozen_queries_path), "plan_sha256": common.digest(Path(config["plan"])),
            "cache_regime": "warm engine and OS cache; full verification and correctness precede measurement",
            "selection_protocol": "tuning timings only; decisions saved before any validation timings",
        }
        (out / "formal_plan_frozen.md").write_bytes(Path(config["plan"]).read_bytes())
        common.save_json(out / "protocol.json", protocol)
        common.save_json(out / "queries.json", queries)
        base = common.read_base(manifest)
        base_digest = common.logical_digest(base)
        all_groups = {}
        for layout in common.LAYOUTS:
            path = Path(layouts[layout]["path"])
            if common.digest(path) != layouts[layout]["file_sha256"]:
                raise AssertionError(f"Parquet file changed: {layout}")
            table = pq.ParquetFile(path).read()
            if common.logical_digest(table) != base_digest:
                raise AssertionError(f"Parquet logical contents changed: {layout}")
            all_groups[layout] = common.extract_groups(path)
        common.save_json(out / "verified_layouts.json", layouts)
        con.register("reference_data", base)
        answers, checks, plans, candidates = {}, [], {}, []
        for query in queries:
            sql, params = common.query_sql(query)
            reference = con.execute(sql, params).fetchone()
            answers[query["query_id"]] = reference
            for layout in common.LAYOUTS:
                sql, params = common.query_sql(query, layouts[layout]["path"])
                actual = con.execute(sql, params).fetchone()
                common.check_answer(actual, reference, pilot_config)
                checks.append({"query_id": query["query_id"], "role": query["role"], "layout": layout,
                               "expected_count": reference[0], "actual_count": actual[0],
                               "expected_mean_sst": reference[1], "actual_mean_sst": actual[1], "passed": True})
                plans[query["query_id"] + "/" + layout] = json.loads(con.execute("EXPLAIN (FORMAT JSON) " + sql, params).fetchone()[1])
                candidates.append({"query_id": query["query_id"], "role": query["role"], "kind": query["kind"],
                                   "window_hours": query["window_hours"], "layout": layout,
                                   **common.candidate_stats(query, all_groups[layout])})
        common.save_json(out / "correctness.json", {"base_rows": base.num_rows, "base_logical_sha256": base_digest, "checks": checks})
        common.save_json(out / "reference_answers.json", answers)
        common.save_json(out / "query_plans.json", plans)
        common.save_csv(out / "candidate_row_groups.csv", candidates)
        counter = [0]
        print("Input contents and all 324 answers verified; starting tuning measurements", flush=True)
        tuning_start = time.perf_counter_ns()
        tuning = measure_role("tuning", roles["tuning"], con, layouts, answers, pilot_config, counter)
        tuning_wall_ms = (time.perf_counter_ns() - tuning_start) / 1e6
        common.save_csv(out / "measurements_tuning.csv", tuning)
        started = time.perf_counter_ns()
        decisions = fit_decisions(tuning, config, pilot_config)
        decisions["calculation_ms"] = (time.perf_counter_ns() - started) / 1e6
        decisions["frozen_at_utc"] = timestamp_now()
        decisions["tuning_measurements_sha256"] = common.digest(out / "measurements_tuning.csv")
        decisions["tuning_phase_wall_ms"] = tuning_wall_ms
        decisions["tuning_candidate_query_ms_including_warmup"] = sum(row["elapsed_ms"] for row in tuning if row["layout"] in config["candidate_layouts"])
        common.save_json(out / "frozen_selection.json", decisions)
        selection_sha = common.digest(out / "frozen_selection.json")
        print("Tuning complete; selection frozen before validation:", [(d["q1_proportion"], d["chosen_layout"]) for d in decisions["decisions"]], flush=True)
        validation_started_at = timestamp_now()
        validation = measure_role("validation", roles["validation"], con, layouts, answers, pilot_config, counter)
        common.save_csv(out / "measurements_validation.csv", validation)
        measurements = tuning + validation
        common.save_csv(out / "measurements.csv", measurements)
        common.save_csv(out / "query_summary.csv", summarize(measurements))
        if common.digest(out / "frozen_selection.json") != selection_sha:
            raise AssertionError("Selection changed after validation began")
        print("Validation timings saved; inspecting candidate groups outside benchmark timers", flush=True)
        details, group_summary = diagnose_groups(queries, layouts, all_groups, answers, config)
        common.save_csv(out / "joint_match_diagnostic.csv", details)
        common.save_csv(out / "joint_match_summary.csv", group_summary)
        counts = Counter((row["role"], row["phase"]) for row in measurements)
        if sum(row["phase"] == "measured" for row in measurements) != 1620 or sum(row["phase"] == "warmup" for row in measurements) != 324:
            raise AssertionError("Missing expected measurements")
        summary = {
            "status": "passed", "completed_at_utc": timestamp_now(), "base_rows": base.num_rows,
            "queries": len(queries), "tuning_queries": len(roles["tuning"]), "validation_queries": len(roles["validation"]),
            "correctness_checks": len(checks), "measured_executions": 1620, "extra_warmups": 324,
            "empty_queries_by_role": {role: sum(answers[q["query_id"]][0] == 0 for q in values) for role, values in roles.items()},
            "selection_sha256_before_validation": selection_sha, "validation_started_at_utc": validation_started_at,
            "measurement_counts": {role + "/" + phase: n for (role, phase), n in counts.items()},
            "diagnostic_query_layout_pairs": len(group_summary),
        }
        common.save_json(status, summary)
        con.close()
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    except Exception as error:
        common.save_json(status, {"status": "failed", "error": str(error), "at_utc": timestamp_now()})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/formal_v1.json"))
    parser.add_argument("--run-id", default="formal_v1")
    args = parser.parse_args()
    if not args.run_id or not all(c.isalnum() or c in "_-" for c in args.run_id):
        parser.error("Use letters, digits, underscores or hyphens for run IDs")
    run(args.config, args.run_id)
