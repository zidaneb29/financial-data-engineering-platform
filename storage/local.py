"""Immutable local artifacts with one atomic commit marker per entity batch."""

import hashlib
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from time import sleep
from typing import Any

from filelock import FileLock

from ingestion.http import JsonResponse, PayloadError
from ingestion.models import Record, decimal_text, utc_now
from storage.manifest import (
    IntegrityError, canonical_bytes, checksum, day, digest, identity, manifest_digest,
    parse_json, raw_reference, require, safe_path, timestamp, token, validate_schema,
)


def json_bytes(value: Any) -> bytes:
    return canonical_bytes(value)


def atomic_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        for delay in (0.05, 0.1, 0.2, 0.4, 0):
            try:
                os.replace(temporary, path)
                break
            except PermissionError as error:
                # A Windows scanner or reader can briefly hold a sharing handle.
                if not delay or getattr(error, "winerror", None) not in {5, 32, 33}:
                    raise
                sleep(delay)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass
class Batch:
    store: "LocalStore"
    source: str
    entity: str
    run_id: str
    start: date
    end: date
    metadata: dict = field(default_factory=dict)
    objects: list[dict] = field(default_factory=list)
    started_at: str = field(default_factory=utc_now)

    def archive(self, endpoint: str, response: JsonResponse, params: dict) -> str:
        identity(self.source, self.entity, self.run_id)
        token(endpoint, "endpoint")
        digest = hashlib.sha256(response.body).hexdigest()
        path = Path("raw", self.source, self.entity, endpoint, f"{digest}.json")
        reference = {
            "endpoint": endpoint, "sha256": digest, "object_key": path.as_posix(),
            "params": params.copy(), "retrieved_at": utc_now(),
        }
        target = raw_reference(self.store.root, reference, self.source, self.entity)
        if target.exists():
            self.store.read_object(reference)
        else:
            atomic_write(target, response.body)
        self.objects.append(reference)
        return path.as_posix()


class LocalStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def lock(self) -> FileLock:
        self.root.mkdir(parents=True, exist_ok=True)
        return FileLock(str(safe_path(self.root, ".ingestion.lock")), timeout=0)

    def manifests(self, source: str, entity: str) -> list[dict]:
        identity(source, entity)
        directory = safe_path(self.root, f"metadata/batches/{source}/{entity}")
        results = []
        seen_runs = set()
        for path in sorted(directory.glob("*.json")):
            reference = path.relative_to(self.root).as_posix()
            manifest = parse_json(safe_path(self.root, reference).read_bytes())
            validate_schema(self.root, manifest)
            require(manifest["manifest"] == reference, "Manifest identity differs from its location")
            require(manifest["run_id"] not in seen_runs, "Duplicate committed entity run")
            seen_runs.add(manifest["run_id"])
            self.validate_batch(manifest, committed=False)
            results.append(manifest)
        return results

    def read_object(self, reference: dict) -> bytes:
        body = raw_reference(self.root, reference).read_bytes()
        if hashlib.sha256(body).hexdigest() != reference["sha256"]:
            raise IntegrityError("Archived source content does not match the manifest checksum")
        require(isinstance(parse_json(body), dict), "Raw source response must be a JSON object")
        return body

    def validate_batch(self, manifest: dict, *, committed: bool = True) -> list[dict]:
        """Validate the complete batch before exposing any normalized rows."""
        validate_schema(self.root, manifest)
        if committed:
            stored = parse_json(safe_path(self.root, manifest["manifest"]).read_bytes())
            require(stored == manifest, "Manifest differs from committed bytes")
        for reference in manifest["objects"]:
            self.read_object(reference)
        all_rows = []
        object_keys = {item["object_key"] for item in manifest["objects"]}
        for dataset, reference in manifest["normalized"].items():
            body = safe_path(self.root, reference).read_bytes()
            if manifest["schema_version"] == 2:
                info = manifest["normalized_files"][dataset]
                require(digest(body) == info["sha256"], "Normalized file checksum mismatch")
                require(len(body) == info["byte_size"], "Normalized file byte size mismatch")
            require(body.endswith(b"\n"), "Incomplete normalized JSON Lines file")
            rows = [parse_json(line) for line in body.splitlines()]
            if manifest["schema_version"] == 2:
                require(len(rows) == info["row_count"], "Normalized file row count mismatch")
            for row in rows:
                self._validate_row(row, manifest, dataset, object_keys)
            all_rows.extend(rows)
        require(len(all_rows) == manifest["counts"]["written"], "Normalized total count mismatch")
        return all_rows

    @staticmethod
    def _validate_row(row: Any, manifest: dict, dataset: str, object_keys: set[str]) -> None:
        require(isinstance(row, dict), "Normalized row must be an object")
        required = {"dataset", "key", "comparison_key", "fingerprint", "ingestion_timestamp", "source"}
        require(required <= set(row), "Missing normalized row fields")
        require(row["source"] == manifest["source"] and row["dataset"] == dataset, "Normalized identity mismatch")
        require(isinstance(row["key"], list) and bool(row["key"])
                and all(value is None or isinstance(value, (str, int)) for value in row["key"]),
                "Invalid normalized natural key")
        require(row["comparison_key"] is None or (
            isinstance(row["comparison_key"], list)
            and all(value is None or isinstance(value, (str, int)) for value in row["comparison_key"])
        ),
                "Invalid normalized comparison key")
        require(timestamp(row["ingestion_timestamp"]) == timestamp(manifest["completed_at"]),
                "Normalized row ingestion timestamp mismatch")
        checksum(row["fingerprint"])
        if object_keys:
            require(row.get("object_key") in object_keys, "Normalized row has no raw batch membership")
            require(type(row.get("source_row")) is int and row["source_row"] >= 0,
                    "Invalid normalized source row")
            if manifest["source"] == "fred":
                require(row.get("series_id") == manifest["entity"], "FRED row entity mismatch")
                require({"snapshot_date", "series_metadata_key", "realtime_start", "realtime_end"} <= set(row),
                        "Missing FRED row provenance")
            else:
                require(row.get("cik") == manifest["entity"], "SEC row entity mismatch")
        # Version 1 has no business-field inventory. Its known lineage fields
        # are excluded to recover the original business fingerprint.
        lineage = {
            "object_key", "source_row", "snapshot_date", "realtime_start", "realtime_end",
            "series_metadata_key", "frame", "filing_matched", "filing_report_date", "selection_eligible",
        }
        fields = row.get("business_fields", sorted(set(row) - required - lineage))
        require(isinstance(fields, list) and bool(fields)
                and all(isinstance(name, str) and name in row for name in fields)
                and len(set(fields)) == len(fields),
                "Invalid normalized business-field inventory")
        business_fields = {
            "observations": {
                "series_id", "observation_date", "units", "frequency", "is_missing", "value", "seasonal_adjustment",
            },
            "filings": {
                "cik", "accession_number", "filing_date", "report_date", "form", "primary_document",
                "is_amendment", "filing_metadata",
            },
            "facts": {
                "cik", "accession_number", "namespace", "tag", "metric", "unit", "normalized_unit",
                "start_date", "end_date", "value", "form", "filed_date", "fiscal_year",
                "fiscal_period", "period_class", "is_amendment",
            },
        }
        require(set(fields) == business_fields[dataset], "Unexpected normalized business fields")
        require(set(row) <= required | lineage | business_fields[dataset] | {"business_fields"},
                "Unexpected normalized row fields")
        require(digest(json_bytes({name: row[name] for name in fields})) == row["fingerprint"],
                "Normalized business fingerprint mismatch")
        if dataset == "observations":
            require(row["key"] == [row["observation_date"]] and row["comparison_key"] is None,
                    "FRED natural key mismatch")
            require(type(row["is_missing"]) is bool and row["is_missing"] == (row["value"] is None),
                    "FRED missing-value flag mismatch")
            day(row["observation_date"])
            if object_keys:
                require(row.get("snapshot_date") == manifest["metadata"].get("snapshot_date")
                        and row.get("series_metadata_key") == manifest["metadata"].get("series_metadata_key"),
                        "FRED row snapshot provenance mismatch")
                require(day(row["realtime_start"]) <= day(row["snapshot_date"]) <= day(row["realtime_end"]),
                        "FRED row vintage interval mismatch")
        else:
            require(type(row["is_amendment"]) is bool and isinstance(row["form"], str)
                    and row["form"] in {"10-K", "10-K/A", "10-Q", "10-Q/A"}
                    and row["is_amendment"] == row["form"].endswith("/A"), "SEC amendment flag mismatch")
            if dataset == "filings":
                require(row["key"] == [row["accession_number"]] and row["comparison_key"] is None,
                        "SEC filing key mismatch")
                day(row["filing_date"])
                if row["report_date"] is not None:
                    day(row["report_date"])
            else:
                require(isinstance(row["value"], str), "SEC fact value must be decimal text")
                expected_key = [row[name] for name in (
                    "accession_number", "namespace", "tag", "unit", "start_date", "end_date",
                )]
                require(row["key"] == expected_key and row["comparison_key"] == expected_key[1:],
                        "SEC fact key mismatch")
                day(row["filed_date"])
                end = day(row["end_date"])
                if row["start_date"] is not None:
                    require(day(row["start_date"]) <= end, "SEC fact duration is reversed")
        if "value" in row and row["value"] is not None:
            try:
                require(decimal_text(row["value"], from_text=True) == row["value"],
                        "Normalized numeric text is not canonical")
            except PayloadError:
                raise IntegrityError("Invalid normalized numeric text") from None

    def reserve_sequence(self, source: str, entity: str, previous: list[dict]) -> int:
        identity(source, entity)
        reference = f"metadata/sequences/{source}/{entity}.json"
        path = safe_path(self.root, reference)
        highest = max((int(Path(item["manifest"]).stem) for item in previous), default=0)
        if path.exists():
            counter = parse_json(path.read_bytes())
            require(isinstance(counter, dict) and set(counter) == {"last_reserved"}
                    and type(counter["last_reserved"]) is int and counter["last_reserved"] >= 0,
                    "Invalid sequence reservation")
            highest = max(highest, counter["last_reserved"])
        # Old journals preserve sequence identities even when a v1 manifest was removed.
        for journal in safe_path(self.root, "metadata/runs").glob("*.json"):
            run = parse_json(safe_path(self.root, journal.relative_to(self.root).as_posix()).read_bytes())
            for item in run.get("entities", []):
                if item.get("source") == source and item.get("entity") == entity and "manifest" in item:
                    reference = item["manifest"]
                    target = safe_path(self.root, reference)
                    require(target.parent == self.root / "metadata" / "batches" / source / entity
                            and len(target.stem) == 12 and target.stem.isdigit(), "Invalid journal manifest reference")
                    highest = max(highest, int(target.stem))
        require(highest < 999999999999, "Manifest sequence exhausted")
        atomic_write(path, json_bytes({"last_reserved": highest + 1}))
        return highest + 1

    def coverage(self, source: str, entity: str, start: date) -> date:
        """Return the first date after contiguous successful request windows."""
        windows = sorted(
            (date.fromisoformat(batch["start"]), date.fromisoformat(batch["end"]))
            for batch in self.manifests(source, entity)
        )
        for lower, upper in windows:
            if lower > start:
                break
            if upper >= start:
                start = upper + timedelta(days=1)
        return start

    def write_run(self, run: dict) -> None:
        identity("fred", "RUN", run["run_id"])
        path = safe_path(self.root, f"metadata/runs/{run['run_id']}.json")
        atomic_write(path, json_bytes(run))

    def recover_runs(self) -> None:
        for path in safe_path(self.root, "metadata/runs").glob("*.json"):
            run = parse_json(safe_path(self.root, path.relative_to(self.root).as_posix()).read_bytes())
            if run["status"] != "running":
                continue
            for result in run["entities"]:
                if result["status"] not in {"running", "pending"}:
                    continue
                committed = next((
                    batch for batch in self.manifests(result["source"], result["entity"])
                    if batch["run_id"] == run["run_id"]
                ), None)
                if committed:
                    result.update(status="success", manifest=committed["manifest"], **committed["counts"])
                else:
                    result["status"] = "interrupted" if result["status"] == "running" else "skipped"
            statuses = {item["status"] for item in run["entities"]}
            run.update(
                status="success" if statuses == {"success"} else "interrupted",
                failed_entities=sum(item["status"] == "failed" for item in run["entities"]),
                counts={
                    name: sum(item.get(name, 0) for item in run["entities"])
                    for name in ("retrieved", "written", "duplicates", "revised")
                },
                recovered_at=utc_now(),
            )
            self.write_run(run)

    def rows(self, manifests: list[dict]):
        for batch in manifests:
            yield from self.validate_batch(batch)

    def commit(self, batch: Batch, records: list[Record]) -> dict:
        identity(batch.source, batch.entity, batch.run_id)
        previous = self.manifests(batch.source, batch.entity)
        require(all(item["run_id"] != batch.run_id for item in previous), "Entity run is already committed")
        sequence = self.reserve_sequence(batch.source, batch.entity, previous)
        index = defaultdict(set)
        comparisons = defaultdict(set)
        for row in self.rows(previous):
            key = (row["dataset"], *row["key"])
            if batch.source == "fred":
                index[key].clear()
            index[key].add(row["fingerprint"])
            if row["comparison_key"] is not None:
                comparisons[tuple(row["comparison_key"])].add(row.get("value"))

        output = defaultdict(list)
        duplicates = revised = 0
        timestamp = utc_now()
        for record in records:
            key = (record.dataset, *record.key)
            fingerprint = hashlib.sha256(json_bytes(record.fields)).hexdigest()
            values = index[key]
            if fingerprint in values:
                duplicates += 1
                continue
            prior_values = comparisons.get(record.comparison_key, set())
            if values or (prior_values and record.fields.get("value") not in prior_values):
                revised += 1
            if batch.source == "fred":
                values.clear()
            values.add(fingerprint)
            output[record.dataset].append({
                **record.fields, **record.lineage, "dataset": record.dataset, "key": record.key,
                "comparison_key": record.comparison_key, "fingerprint": fingerprint,
                "business_fields": sorted(record.fields),
                "ingestion_timestamp": timestamp, "source": batch.source,
            })
        normalized = {}
        normalized_files = {}
        for dataset, rows in output.items():
            require(dataset in ({"observations"} if batch.source == "fred" else {"filings", "facts"}),
                    "Unexpected normalized dataset")
            path = Path("processed", batch.source, batch.entity, batch.run_id, f"{dataset}.jsonl")
            body = b"".join(map(json_bytes, rows))
            atomic_write(safe_path(self.root, path.as_posix()), body)
            normalized[dataset] = path.as_posix()
            normalized_files[dataset] = {"sha256": digest(body), "byte_size": len(body), "row_count": len(rows)}
        path = Path("metadata", "batches", batch.source, batch.entity, f"{sequence:012}.json")
        manifest = {
            "schema_version": 2, "run_id": batch.run_id, "source": batch.source,
            "entity": batch.entity, "started_at": batch.started_at, "completed_at": timestamp,
            "start": batch.start.isoformat(), "end": batch.end.isoformat(),
            "metadata": batch.metadata, "objects": batch.objects, "normalized": normalized,
            "normalized_files": normalized_files,
            "manifest": path.as_posix(), "status": "success",
            "counts": {
                "retrieved": len(records), "written": len(records) - duplicates,
                "duplicates": duplicates, "revised": revised,
            },
        }
        manifest["manifest_sha256"] = manifest_digest(manifest)
        self.validate_batch(manifest, committed=False)
        target = safe_path(self.root, path.as_posix())
        require(not target.exists(), "Manifest sequence is already occupied")
        atomic_write(target, json_bytes(manifest))
        return manifest
