"""Validate a bounded local replay and compare it with an approved Snowflake build."""

import argparse
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from storage.local import LocalStore, json_bytes
from storage.manifest import digest, parse_json, require
from storage.transfer import prepare_batch


RAW_COUNTS = {
    "raw.source_object": 4,
    "raw.batch_object": 8,
    "raw.ingestion_record": 91,
    "raw.sec_snapshot_member": 136,
    "raw.numeric_quarantine": 0,
    "ops.batch_load": 4,
}
DBT_RELATIONS = (
    "scope.issuer_scope", "scope.series_scope",
    "staging.stg_batches", "staging.stg_batch_objects", "staging.stg_fred_observations",
    "staging.stg_sec_filings", "staging.stg_sec_facts", "staging.stg_sec_members",
    "analytics.fact_economic_observations", "analytics.sec_selected_snapshots",
    "analytics.sec_financial_candidates", "analytics.fact_company_financials",
)
NAMES = {"database": "FDEP_PARITY_DB", "warehouse": "FDEP_PARITY_WH", "schema": "FDEP_PARITY"}


def read_relation(cursor: Any, relation: str) -> tuple[tuple[str, ...], list[tuple]]:
    result = cursor.execute(f"select * from {relation}")
    columns = tuple(column[0].lower() for column in result.description)
    return columns, result.fetchall()


def verify_archive(db: duckdb.DuckDBPyConnection, archive: Path) -> None:
    store = LocalStore(archive)
    for relation, expected in RAW_COUNTS.items():
        actual = db.execute(f"select count(*) from {relation}").fetchone()[0]
        require(actual == expected, f"{relation} row count: {actual}, expected {expected}")
    ledger = db.execute("""
        select batch_id, manifest_hash, receipt_hash, manifest_text, receipt_text
        from ops.batch_load order by batch_id
    """).fetchall()
    expected_objects = set()
    for batch_id, manifest_hash, receipt_hash, manifest_text, receipt_text in ledger:
        receipt = parse_json(receipt_text.encode())
        namespace = receipt["identity"]["namespace"]
        require(namespace != "fixture", "Expected the genuine Phase 3B archive")
        batch = prepare_batch(store, parse_json(manifest_text.encode()), namespace)
        require(
            batch.batch_id == batch_id and batch.receipt == receipt
            and batch.receipt["manifest_file_sha256"] == manifest_hash
            and digest(json_bytes(receipt)) == receipt_hash,
            "Local replay ledger differs from validated archive",
        )
        expected_objects.update(
            (
                digest(json_bytes({"namespace": namespace, "key": obj["object_key"]})),
                f"{namespace}/{obj['object_key']}", obj["sha256"],
            )
            for obj in batch.manifest["objects"]
        )
    objects = db.execute("select object_id, object_key, sha256, sha256(payload_text) from raw.source_object")
    records = objects.fetchall()
    require({row[:3] for row in records} == expected_objects, "Local replay object keys differ from archive")
    require(all(expected == calculated for _, _, expected, calculated in records), "Local RAW payload hash mismatch")
    print("Validated four Phase 3B manifests and four archived RAW bodies")


def connect_snowflake() -> Any:
    import snowflake.connector

    config = {key: os.environ[f"FDEP_DBT_{key.upper()}"] for key in ("account", "user", "role", *NAMES)}
    require(all(config[key] == value for key, value in NAMES.items()), "Expected the dedicated parity target")
    config.pop("schema")
    return snowflake.connector.connect(
        **config, authenticator="externalbrowser", paramstyle="qmark", autocommit=False,
        arrow_number_to_decimal=True,
        login_timeout=60, network_timeout=120,
        session_parameters={"TIMEZONE": "UTC", "QUERY_TAG": "FDEP_PHASE7_PARITY",
                            "STATEMENT_TIMEOUT_IN_SECONDS": 120, "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": 30},
    )


def load_raw(db: duckdb.DuckDBPyConnection, connection: Any, cursor: Any) -> None:
    cursor.execute("begin")
    try:
        for relation in RAW_COUNTS:
            cursor.execute(f"select count(*) from {relation}")
            require(cursor.fetchone()[0] == 0, f"Expected an empty dedicated table: {relation}")
        for relation in RAW_COUNTS:
            _, records = read_relation(db, relation)
            if relation == "raw.source_object":
                for object_id, key, sha256, payload in records:
                    cursor.execute(f"insert into {relation} values (?, ?, ?, ?)", (object_id, key, sha256, ""))
                    # Keep each bound body fragment well below the Snowflake query size guidance.
                    for offset in range(0, len(payload), 64_000):
                        cursor.execute(
                            f"update {relation} set payload_text = payload_text || ? where object_id = ?",
                            (payload[offset:offset + 64_000], object_id),
                        )
                continue
            for offset in range(0, len(records), 25):
                group = records[offset:offset + 25]
                placeholders = "(" + ", ".join("?" for _ in group[0]) + ")"
                values = tuple(
                    ("TIMESTAMP_TZ", value) if isinstance(value, datetime) else value
                    for row in group for value in row
                )
                cursor.execute(f"insert into {relation} values " + ", ".join([placeholders] * len(group)), values)
        compare(db, cursor, include_dbt=False)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def compare(local: Any, remote: Any, *, include_dbt: bool = True, remote_prefix: str = "fdep_parity") -> None:
    relations = [(name, name) for name in RAW_COUNTS]
    if include_dbt:
        relations.extend((f"fdep_{name}", f"{remote_prefix}_{name}") for name in DBT_RELATIONS)
    for local_name, remote_name in relations:
        columns, expected = read_relation(local, local_name)
        actual_columns, actual = read_relation(remote, remote_name)
        require(columns == actual_columns, f"{local_name} column contract mismatch")
        require(
            not any(isinstance(value, float) for row in expected + actual for value in row),
            f"{local_name} returned an inexact floating-point projection",
        )
        delta = Counter(expected) - Counter(actual)
        extra = Counter(actual) - Counter(expected)
        require(not delta and not extra,
                f"{local_name}: {len(expected)} expected, {len(actual)} actual, "
                f"{delta.total()} missing/changed, {extra.total()} unexpected/changed")
        print(f"{local_name}: {len(expected)} exact rows")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("preflight", "load", "compare"))
    parser.add_argument("database", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--approved-cloud", action="store_true")
    args = parser.parse_args()
    if args.stage != "preflight" and not args.approved_cloud:
        parser.error("Cloud execution requires separate authorization and --approved-cloud")
    with duckdb.connect(str(args.database), read_only=True) as local:
        verify_archive(local, args.archive)
        if args.stage == "preflight":
            for name in DBT_RELATIONS:
                columns, values = read_relation(local, f"fdep_{name}")
                print(f"fdep_{name}: {len(values)} rows across {len(columns)} columns")
            return
        with connect_snowflake() as remote, remote.cursor() as cursor:
            if args.stage == "load":
                load_raw(local, remote, cursor)
            else:
                compare(local, cursor)


if __name__ == "__main__":
    main()
