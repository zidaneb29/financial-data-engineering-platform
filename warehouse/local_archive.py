"""Load an explicitly scoped local archive into the DuckDB RAW/OPS contract."""

import logging
from decimal import Decimal
from pathlib import Path

import duckdb

from ingestion.models import utc_now
from storage.local import LocalStore, json_bytes
from storage.manifest import digest, require
from storage.transfer import PreparedBatch, prepare_batch
from warehouse.batch_rows import batch_records, payload_text


LOGGER = logging.getLogger(__name__)
DDL = Path(__file__).resolve().parent / "sql/001_raw.sql"


def initialize_raw(db: duckdb.DuckDBPyConnection) -> None:
    ddl = DDL.read_text(encoding="utf-8")
    db.execute(ddl.replace("TIMESTAMP_TZ", "TIMESTAMPTZ").replace("NUMBER(", "DECIMAL(").replace(
        "LIKE RAW.INGESTION_RECORD", "AS SELECT * FROM RAW.INGESTION_RECORD WHERE FALSE",
    ))


def insert_rows(db: duckdb.DuckDBPyConnection, table: str, rows: list[tuple]) -> None:
    for offset in range(0, len(rows), 250):
        group = rows[offset:offset + 250]
        placeholders = "(" + ", ".join("?" for _ in group[0]) + ")"
        parameters = [str(value) if isinstance(value, Decimal) else value for row in group for value in row]
        db.execute(f"insert into {table} values " + ", ".join([placeholders] * len(group)), parameters)


def write_batch(
    db: duckdb.DuckDBPyConnection, store: LocalStore, batch: PreparedBatch, objects: set[str],
) -> dict[str, int]:
    namespace = batch.receipt["identity"]["namespace"]
    requests = []
    for index, item in enumerate(batch.manifest["objects"]):
        key = item["object_key"]
        object_id = digest(json_bytes({"namespace": namespace, "key": key}))
        if object_id not in objects:
            db.execute("insert into raw.source_object values (?, ?, ?, ?)", (
                object_id, f"{namespace}/{key}", item["sha256"], batch.artifacts[key].decode("utf-8"),
            ))
            objects.add(object_id)
        requests.append((
            batch.batch_id, index, object_id, item["endpoint"], payload_text(item["params"]), item["retrieved_at"],
        ))
    changes, members, quarantine = batch_records(store, batch)
    for table, records in (
        ("raw.batch_object", requests), ("raw.ingestion_record", changes),
        ("raw.sec_snapshot_member", members), ("raw.numeric_quarantine", quarantine),
    ):
        insert_rows(db, table, records)
    counts = dict(requests=len(requests), changes=len(changes), members=len(members), quarantined=len(quarantine))
    insert_rows(db, "ops.batch_load", [(
        batch.batch_id, batch.receipt["manifest_file_sha256"], digest(json_bytes(batch.receipt)),
        payload_text(batch.manifest), payload_text(batch.receipt), payload_text(counts), utc_now(),
    )])
    return counts


def load_archive(
    store: LocalStore, output: Path, entities: list[tuple[str, str]], *,
    window: tuple[str, str] | None, namespace: str,
) -> None:
    require(output != store.root and not output.is_relative_to(store.root), "Place the database outside the archive")
    require(not output.exists(), "RAW database path must be new")
    objects: set[str] = set()
    batches = 0
    with duckdb.connect(str(output)) as db, store.lock():
        initialize_raw(db)
        db.execute("begin transaction")
        for source, entity in entities:
            manifests = store.manifests(source, entity)
            if window is not None:
                # A changed-only FRED archive needs its predecessors. A dedicated archive
                # keeps all committed batches in the same requested window.
                require(bool(manifests), f"Missing archive coverage for {source}/{entity}")
                require(all((m["start"], m["end"]) == window for m in manifests),
                        f"Unexpected window in archive for {source}/{entity}")
            for manifest in manifests:
                batch = prepare_batch(store, manifest, namespace)
                counts = write_batch(db, store, batch, objects)
                batches += 1
                LOGGER.info(json_bytes({
                    "event": "local_archive_batch", "source": source, "entity": entity,
                    "run_id": manifest["run_id"], "batch_id": batch.batch_id, **counts,
                }).decode().strip())
        require(batches > 0, "No configured committed source batches were found")
        db.execute("commit")
