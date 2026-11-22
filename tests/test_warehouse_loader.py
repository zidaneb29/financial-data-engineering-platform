from decimal import Decimal
from pathlib import Path

import pytest

from ingestion.pipeline import run_ingestion
from storage.local import LocalStore
from storage.manifest import IntegrityError, parse_json
from storage.transfer import CloudError, S3Transfer
from warehouse.loader import SnowflakeLoader
from warehouse.numeric import NumericRangeError, checked_decimal
from cloud_doubles import MemoryS3, MemoryWarehouse
from test_cloud_transfer import transferred
from test_sec import CIK, ORIGINAL_FILING, facts, fact, submissions, task as sec_task
from test_local_ingestion import task


def loader_fixture(tmp_path, *, value="1"):
    store, manifest, client, transfer = transferred(tmp_path, value=value)
    transfer.transfer(manifest)
    database = MemoryWarehouse()
    loader = SnowflakeLoader(store, transfer, database.connect, target_id="test-account/database")
    return store, manifest, client, transfer, database, loader


@pytest.mark.parametrize("text", ["0", "-0", "99999999999999999999999999.999999999999", "0.000000000001", "-12.1250"])
def test_exact_numeric_boundaries(text):
    assert checked_decimal(text) == Decimal(text)


@pytest.mark.parametrize("text", ["100000000000000000000000000", "0.0000000000001",
                                       "123456789012345678901234567890123456789", "NaN", "Infinity", "bad", 1.2])
def test_unsupported_numeric_values_are_rejected(text):
    with pytest.raises(NumericRangeError):
        checked_decimal(text)


def test_transactional_load_replay_and_provenance(tmp_path):
    store, manifest, _client, _transfer, db, loader = loader_fixture(tmp_path)
    first = loader.load(manifest)
    assert first["counts"] == {"changes": 1, "members": 0, "requests": 2, "quarantined": 0}
    row, = db.tables["RAW.INGESTION_RECORD"]
    payload = parse_json(row["PAYLOAD_TEXT"].encode())
    assert payload["object_key"] == manifest["objects"][1]["object_key"]
    assert row["VALUE_TEXT"] == "1" and row["VALUE_NUMBER"] == Decimal("1")
    before = {name: len(rows) for name, rows in db.tables.items()}
    assert loader.load(manifest)["replay"]
    assert {name: len(rows) for name, rows in db.tables.items()} == before
    assert db.sql[:2] == ["BEGIN TRANSACTION", "UPDATE OPS.LOAD_MUTEX SET VERSION = VERSION + 1 WHERE LOCK_ID = 1"]
    assert not any(sql.startswith(("CREATE", "COPY", "PUT", "ALTER")) for sql in db.sql)
    assert parse_json(loader._journal_path(first["batch_id"]).read_bytes())["attempts"][-1]["status"] == "success"


def test_failed_mid_load_rolls_back_and_retries_on_fresh_connection(tmp_path):
    _store, manifest, _client, _transfer, db, loader = loader_fixture(tmp_path)
    db.fail_table = "OPS.BATCH_LOAD"
    with pytest.raises(CloudError):
        loader.load(manifest)
    assert db.tables == {}
    report = loader.load(manifest)
    assert report["status"] == "success" and not report["replay"]
    assert db.connects == 2
    assert len(db.tables["RAW.INGESTION_RECORD"]) == 1


def test_unknown_commit_is_reconciled_from_warehouse_ledger(tmp_path):
    _store, manifest, _client, _transfer, db, loader = loader_fixture(tmp_path)
    db.ambiguous_commit = True
    with pytest.raises(CloudError):
        loader.load(manifest)
    assert len(db.tables["OPS.BATCH_LOAD"]) == 1
    report = loader.load(manifest)
    assert report["replay"] and len(db.tables["RAW.INGESTION_RECORD"]) == 1
    journal = parse_json(loader._journal_path(report["batch_id"]).read_bytes())
    assert [attempt["status"] for attempt in journal["attempts"]] == ["unknown", "success"]


def test_raw_load_preserves_overflow_text_and_quarantines_projection(tmp_path):
    value = "123456789012345678901234567890123456789"
    _store, manifest, _client, _transfer, db, loader = loader_fixture(tmp_path, value=value)
    report = loader.load(manifest)
    assert report["numeric_status"] == "quarantined"
    row, = db.tables["RAW.INGESTION_RECORD"]
    assert row["VALUE_TEXT"] == value and row["VALUE_NUMBER"] is None
    rejected, = db.tables["RAW.NUMERIC_QUARANTINE"]
    assert rejected["VALUE_TEXT"] == value
    assert parse_json(rejected["PAYLOAD_TEXT"].encode())["value"] == value


def test_warehouse_reconciliation_rejects_missing_rows_and_invalid_mutex(tmp_path):
    _store, manifest, _client, _transfer, db, loader = loader_fixture(tmp_path)
    loader.load(manifest)
    db.tables["RAW.INGESTION_RECORD"].clear()
    with pytest.raises(IntegrityError, match="counts"):
        loader.load(manifest)
    db.mutex_rows = 0
    with pytest.raises(IntegrityError, match="mutex"):
        loader.load(manifest)


def test_remote_incomplete_batch_never_connects_to_warehouse(tmp_path):
    _store, manifest, client, transfer, db, loader = loader_fixture(tmp_path)
    client.objects.pop((transfer.bucket, transfer.key(manifest["objects"][0]["object_key"])))
    with pytest.raises(IntegrityError):
        loader.load(manifest)
    assert db.connects == 0


def test_sec_membership_preserves_unchanged_and_withdrawn_history(tmp_path, fake_http):
    store = LocalStore(tmp_path)
    for candidates in ([fact()], [fact()], []):
        client, _ = fake_http([submissions(ORIGINAL_FILING), facts({"Revenues": {"USD": candidates}})])
        run_ingestion(store, [sec_task(client)], mode="incremental")
    batches = store.manifests("sec", CIK)
    transfer = S3Transfer(store, MemoryS3(), bucket="test-bucket", namespace="portfolio", sleep=lambda _delay: None)
    db = MemoryWarehouse()
    loader = SnowflakeLoader(store, transfer, db.connect, target_id="test-target")
    reports = []
    for batch in batches:
        transfer.transfer(batch)
        reports.append(loader.load(batch))
    assert [report["counts"]["changes"] for report in reports] == [2, 0, 0]
    assert [report["counts"]["members"] for report in reports] == [2, 2, 1]
    latest_id = reports[-1]["batch_id"]
    assert not [
        row for row in db.tables["RAW.SEC_SNAPSHOT_MEMBER"]
        if row["BATCH_ID"] == latest_id and row["DATASET"] == "facts"
    ]
    assert any(row["DATASET"] == "facts" for row in db.tables["RAW.INGESTION_RECORD"])


def test_schema_is_separate_and_preserves_exact_payload_text():
    sql = (Path(__file__).resolve().parents[1] / "warehouse/sql/001_raw.sql").read_text()
    assert "VALUE_NUMBER NUMBER(38,12)" in sql
    assert "PAYLOAD_TEXT VARCHAR(16777216)" in sql
    assert "PARSE_JSON" not in sql


def test_reused_warehouse_raw_objects_are_verified_before_new_batch_commit(tmp_path):
    store, manifest, _client, transfer, db, loader = loader_fixture(tmp_path)
    loader.load(manifest)
    db.tables["RAW.SOURCE_OBJECT"][0]["PAYLOAD_TEXT"] = "{}"
    run_ingestion(store, [task()], mode="incremental")
    later = store.manifests("fred", "TEST")[-1]
    transfer.transfer(later)
    with pytest.raises(IntegrityError, match="raw object"):
        loader.load(later)
    assert len(db.tables["OPS.BATCH_LOAD"]) == 1


def test_post_commit_checkpoint_failure_reconciles_without_duplicate_records(tmp_path, monkeypatch):
    from warehouse import loader as loader_module

    _store, manifest, _client, _transfer, db, loader = loader_fixture(tmp_path)
    write = loader_module.atomic_write

    def fail_local_success(path, body):
        if "loads" in path.parts and parse_json(body)["attempts"][-1]["status"] == "success":
            raise OSError("injected local checkpoint failure")
        write(path, body)

    with monkeypatch.context() as patch:
        patch.setattr(loader_module, "atomic_write", fail_local_success)
        with pytest.raises(OSError):
            loader.load(manifest)
    assert len(db.tables["OPS.BATCH_LOAD"]) == 1
    assert loader.load(manifest)["replay"]
    assert len(db.tables["RAW.INGESTION_RECORD"]) == 1


@pytest.mark.parametrize(("precision", "scale"), [(39, 12), (38, 38), (5, 6)])
def test_invalid_warehouse_numeric_type_specifications(precision, scale):
    with pytest.raises(ValueError, match="specification"):
        checked_decimal("1", precision=precision, scale=scale)
