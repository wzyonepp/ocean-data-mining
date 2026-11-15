#!/usr/bin/env python3
"""Restore hash-pinned inputs without overwriting committed result manifests.

CSV downloads and generated Parquet files live only under data/. --verify-rebuild
also recreates existing Parquet inputs in temporary files and checks their hashes.
"""

import argparse
import json
import random
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

import run_parquet_pilot as common


def restore(verify_rebuild, log_path):
    config_path = Path("config/pilot_v1.json")
    config = json.loads(config_path.read_text())
    protocol = json.loads(Path("results/pilot_v1/protocol.json").read_text())
    manifest_path = Path(config["data_manifest"])
    manifest = json.loads(manifest_path.read_text())
    layouts = json.loads(Path("results/pilot_v1/layout_manifest.json").read_text())
    if common.digest(config_path) != protocol["config_sha256"] or common.digest(manifest_path) != protocol["source_manifest_sha256"]:
        raise ValueError("Committed input snapshot definitions have changed; restore them before replication")
    if pa.__version__ != protocol["environment"]["pyarrow"] or duckdb.__version__ != protocol["environment"]["duckdb"]:
        raise ValueError("Install requirements-formal.txt to match the recorded reader/writer versions")
    csv_log = []
    for source in manifest["files"]:
        path = Path(source["local_file"])
        if path.exists():
            if common.digest(path) != source["sha256"]:
                raise ValueError(f"Local input hash mismatch; refusing to overwrite: {path}")
            csv_log.append({"path": str(path), "action": "reused", "sha256": source["sha256"]})
            continue
        urls = list(dict.fromkeys([source["url"], source["url"].replace("upwell.pfeg.noaa.gov", "coastwatch.pfeg.noaa.gov")]))
        errors = []
        for url in urls:
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "MarineDataMiningCourse/1.0"})
                with urllib.request.urlopen(request, timeout=60) as response:
                    content = response.read()
                if common.hashlib.sha256(content).hexdigest() != source["sha256"]:
                    raise ValueError("Upstream response differs from the recorded data snapshot")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                csv_log.append({"path": str(path), "action": "downloaded", "url": url,
                                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(), "sha256": source["sha256"]})
                break
            except Exception as error:
                errors.append(str(error))
        else:
            raise RuntimeError(f"Cannot restore exact input snapshot: {path}: {errors}")
    needed = []
    layout_log = []
    for layout in common.LAYOUTS:
        path = Path(layouts[layout]["path"])
        if path.exists() and common.digest(path) != layouts[layout]["file_sha256"]:
            raise ValueError(f"Existing Parquet hash mismatch; refusing to overwrite: {path}")
        if path.exists() and not verify_rebuild:
            layout_log.append({"layout": layout, "action": "reused", "sha256": layouts[layout]["file_sha256"]})
        else:
            needed.append(layout)
    if needed:
        base = common.read_base(manifest)
        for layout in needed:
            if layout == "random":
                indices = list(range(base.num_rows))
                random.Random(config["random_seed"]).shuffle(indices)
                table = base.take(pa.array(indices, type=pa.uint32()))
            else:
                keys = common.CANONICAL_KEYS if layout == "station_first" else list(reversed(common.CANONICAL_KEYS))
                table = base.sort_by(keys)
            path = Path(layouts[layout]["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".restore-check.parquet")
            if temporary.exists():
                raise ValueError(f"Temporary input already exists; inspect it first: {temporary}")
            pq.write_table(table.combine_chunks(), temporary, **config["writer"])
            regenerated_sha = common.digest(temporary)
            if regenerated_sha != layouts[layout]["file_sha256"]:
                raise ValueError(f"Reconstructed layout differs; temporary file retained: {temporary}")
            action = "rebuilt_and_verified_against_existing" if path.exists() else "restored"
            if path.exists():
                temporary.unlink()
            else:
                temporary.replace(path)
            layout_log.append({"layout": layout, "action": action, "sha256": regenerated_sha})
    result = {"verified_at_utc": datetime.now(timezone.utc).isoformat(), "csv_files": csv_log,
              "parquet_files": layout_log, "committed_result_manifests_modified": False}
    common.save_json(log_path, result)
    print(json.dumps({"csv_files_verified": len(csv_log), "parquet_files_verified": len(layout_log),
                      "rebuild_verification": verify_rebuild, "log": str(log_path)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-rebuild", action="store_true")
    parser.add_argument("--log", type=Path, default=Path("data/snapshot_restore_log.json"))
    args = parser.parse_args()
    restore(args.verify_rebuild, args.log)
