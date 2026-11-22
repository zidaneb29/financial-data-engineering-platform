"""Small-batch Snowflake RAW loader using DML-only transactions."""

import logging
from typing import Callable
from uuid import uuid4

from ingestion.models import utc_now
from storage.local import LocalStore, atomic_write, json_bytes
from storage.manifest import IntegrityError, digest, parse_json, require, safe_path
from storage.transfer import CloudError, PreparedBatch, S3Transfer, prepare_batch
from warehouse.batch_rows import TEXT_LIMIT, batch_records, payload_text as _text


LOGGER = logging.getLogger(__name__)


class SnowflakeLoader:
    def __init__(
        self, store: LocalStore, transfer: S3Transfer, connection_factory: Callable,
        *, target_id: str,
    ):
        require(bool(target_id), "Warehouse target identity is required")
        self.store, self.transfer = store, transfer
        self.connection_factory = connection_factory
        # Target identity must include account, database and role/config context.
        self.target = digest(target_id.encode("utf-8"))

    def _journal_path(self, batch_id: str):
        return safe_path(self.store.root, f"metadata/loads/{self.target}/{batch_id}.json")

    def _journal(self, batch: PreparedBatch) -> dict:
        path = self._journal_path(batch.batch_id)
        pin = digest(json_bytes(batch.receipt))
        journal = parse_json(path.read_bytes()) if path.exists() else {
            "batch_id": batch.batch_id, "receipt_sha256": pin, "attempts": [],
        }
        require(journal["receipt_sha256"] == pin, "Warehouse batch identity changed after pinning")
        return journal

    def _records(self, batch: PreparedBatch) -> tuple[list[tuple], list[tuple], list[tuple]]:
        return batch_records(self.store, batch)

    @staticmethod
    def _insert(cursor, table: str, columns: str, rows: list[tuple]) -> None:
        # Client-side pyformat bindings with execute avoid connector executemany
        # paths that can create temporary stages for sufficiently large binds.
        for offset in range(0, len(rows), 100):
            group = rows[offset:offset + 100]
            placeholders = "(" + ",".join(["%s"] * len(group[0])) + ")"
            sql = f"INSERT INTO {table} ({columns}) VALUES " + ",".join([placeholders] * len(group))
            cursor.execute(sql, tuple(value for row in group for value in row))

    @staticmethod
    def _reconcile(cursor, batch_id: str, expected: dict) -> dict:
        actual = {}
        tables = {
            "changes": "RAW.INGESTION_RECORD", "members": "RAW.SEC_SNAPSHOT_MEMBER",
            "requests": "RAW.BATCH_OBJECT", "quarantined": "RAW.NUMERIC_QUARANTINE",
        }
        for name, table in tables.items():
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE BATCH_ID = %s", (batch_id,))
            actual[name] = cursor.fetchone()[0]
        require(actual == expected, "Warehouse batch counts do not reconcile")
        return actual

    def load(self, manifest: dict) -> dict:
        with self.store.lock():
            batch = prepare_batch(self.store, manifest, self.transfer.namespace)
            journal = self._journal(batch)
            for previous in journal["attempts"]:
                if previous["status"] == "running":
                    previous["status"] = "unknown"
            attempt = {"attempt_id": uuid4().hex, "started_at": utc_now(), "status": "running"}
            journal["attempts"].append(attempt)
            atomic_write(self._journal_path(batch.batch_id), json_bytes(journal))
            connection = cursor = None
            commit_started = False
            try:
                batch = self.transfer.verified_batch(manifest)
                changes, members, quarantine = self._records(batch)
                expected = {
                    "changes": len(changes), "members": len(members),
                    "requests": len(manifest["objects"]), "quarantined": len(quarantine),
                }
                connection = self.connection_factory()
                cursor = connection.cursor()
                cursor.execute("BEGIN TRANSACTION")
                # Standard-table uniqueness constraints are not enforced. This
                # pre-existing mutex row serializes cooperating loader sessions.
                cursor.execute("UPDATE OPS.LOAD_MUTEX SET VERSION = VERSION + 1 WHERE LOCK_ID = 1")
                require(cursor.rowcount == 1, "Warehouse load mutex must contain exactly one initialized row")
                cursor.execute(
                    "SELECT MANIFEST_HASH, RECEIPT_HASH, COUNTS_TEXT FROM OPS.BATCH_LOAD WHERE BATCH_ID = %s",
                    (batch.batch_id,),
                )
                entries = cursor.fetchall()
                require(len(entries) <= 1, "Duplicate warehouse commit ledger entries")
                replay = bool(entries)
                if replay:
                    manifest_hash, receipt_hash, counts_text = entries[0]
                    require(manifest_hash == batch.receipt["manifest_file_sha256"]
                            and receipt_hash == digest(json_bytes(batch.receipt))
                            and parse_json(counts_text.encode()) == expected, "Warehouse ledger pin mismatch")
                else:
                    self._write(cursor, batch, changes, members, quarantine, expected)
                actual = self._reconcile(cursor, batch.batch_id, expected)
                commit_started = True
                connection.commit()
            except Exception as error:
                if connection is not None:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                attempt.update(
                    status="unknown" if commit_started else "failed",
                    error_code="integrity" if isinstance(error, IntegrityError) else "warehouse_error",
                    completed_at=utc_now(),
                )
                atomic_write(self._journal_path(batch.batch_id), json_bytes(journal))
                if isinstance(error, IntegrityError):
                    raise
                raise CloudError("Warehouse load failed or its commit is unknown. Retry with a fresh connection to reconcile.") from None
            finally:
                if cursor is not None:
                    try:
                        cursor.close()
                    except Exception:
                        pass
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        pass
            attempt.update(status="success", completed_at=utc_now(), replay=replay, counts=actual)
            atomic_write(self._journal_path(batch.batch_id), json_bytes(journal))
            report = {
                "batch_id": batch.batch_id, "status": "success", "replay": replay,
                "counts": actual, "numeric_status": "quarantined" if quarantine else "exact",
            }
            LOGGER.info(json_bytes({"event": "warehouse_load_complete", **report}).decode().strip())
            return report

    def _write(self, cursor, batch, changes, members, quarantine, expected):
        namespace = batch.receipt["identity"]["namespace"]
        for reference in batch.manifest["objects"]:
            key = reference["object_key"]
            object_id = digest(json_bytes({"namespace": namespace, "key": key}))
            body = batch.artifacts[key]
            require(len(body) <= TEXT_LIMIT, "Raw object exceeds warehouse text-size contract")
            cursor.execute(
                "MERGE INTO RAW.SOURCE_OBJECT T USING "
                "(SELECT %s AS OBJECT_ID, %s AS OBJECT_KEY, %s AS SHA256, %s AS PAYLOAD_TEXT) S "
                "ON T.OBJECT_ID = S.OBJECT_ID WHEN NOT MATCHED THEN INSERT "
                "(OBJECT_ID, OBJECT_KEY, SHA256, PAYLOAD_TEXT) VALUES "
                "(S.OBJECT_ID, S.OBJECT_KEY, S.SHA256, S.PAYLOAD_TEXT)",
                (object_id, f"{namespace}/{key}", reference["sha256"], body.decode("utf-8")),
            )
            cursor.execute(
                "SELECT SHA256, PAYLOAD_TEXT FROM RAW.SOURCE_OBJECT WHERE OBJECT_ID = %s", (object_id,),
            )
            stored = cursor.fetchall()
            require(len(stored) == 1 and stored[0][0] == reference["sha256"]
                    and digest(stored[0][1].encode("utf-8")) == reference["sha256"],
                    "Warehouse raw object content does not reconcile")
        requests = [
            (
                batch.batch_id, index, digest(json_bytes({"namespace": namespace, "key": item["object_key"]})),
                item["endpoint"], _text(item["params"]), item["retrieved_at"],
            )
            for index, item in enumerate(batch.manifest["objects"])
        ]
        self._insert(cursor, "RAW.BATCH_OBJECT",
                     "BATCH_ID, REQUEST_INDEX, OBJECT_ID, ENDPOINT, PARAMS_TEXT, RETRIEVED_AT", requests)
        columns = "BATCH_ID, DATASET, ROW_ORDINAL, SOURCE, ENTITY, PAYLOAD_TEXT, VALUE_TEXT, VALUE_NUMBER"
        self._insert(cursor, "RAW.INGESTION_RECORD", columns, changes)
        self._insert(cursor, "RAW.SEC_SNAPSHOT_MEMBER", columns, members)
        self._insert(cursor, "RAW.NUMERIC_QUARANTINE",
                     "BATCH_ID, RECORD_KIND, ROW_ORDINAL, VALUE_TEXT, ERROR_CODE, PAYLOAD_TEXT", quarantine)
        self._insert(cursor, "OPS.BATCH_LOAD",
                     "BATCH_ID, MANIFEST_HASH, RECEIPT_HASH, MANIFEST_TEXT, RECEIPT_TEXT, COUNTS_TEXT, COMMITTED_AT",
                     [(
                         batch.batch_id, batch.receipt["manifest_file_sha256"],
                         digest(json_bytes(batch.receipt)), _text(batch.manifest), _text(batch.receipt),
                         _text(expected), utc_now(),
                     )])
