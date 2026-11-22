import copy

import pytest

from ingestion.pipeline import run_ingestion
from storage.local import LocalStore, json_bytes
from storage.manifest import IntegrityError, manifest_digest, parse_json
from storage.transfer import CloudError, S3Transfer, prepare_batch
from cloud_doubles import MemoryS3
from test_local_ingestion import task


def transferred(tmp_path, *, value="1"):
    store = LocalStore(tmp_path)
    run_ingestion(store, [task(value=value)], mode="backfill")
    manifest, = store.manifests("fred", "TEST")
    client = MemoryS3()
    transfer = S3Transfer(store, client, bucket="test-bucket", namespace="portfolio", sleep=lambda _delay: None)
    return store, manifest, client, transfer


def test_deterministic_keys_readback_and_repeat_transfer(tmp_path):
    store, manifest, client, transfer = transferred(tmp_path)
    first = transfer.transfer(manifest)
    expected = len(prepare_batch(store, manifest, "portfolio").artifacts)
    assert first["uploaded"] == expected
    assert first["ready_key"] == f"portfolio/ready/{first['batch_id']}.json"
    assert all(key.startswith("portfolio/") for key in client.puts)
    puts = list(client.puts)
    replay = transfer.transfer(manifest)
    assert replay["uploaded"] == 0 and client.puts == puts
    batch = transfer.verified_batch(manifest)
    assert batch.batch_id == first["batch_id"]
    assert len(client.gets) > len(puts)
    state = parse_json(transfer._state_path(batch.batch_id).read_bytes())
    assert state["status"] == "success" and len(state["attempts"]) == 2


def test_corrupt_local_batch_is_rejected_before_any_cloud_call(tmp_path):
    store, manifest, client, transfer = transferred(tmp_path)
    (store.root / manifest["normalized"]["observations"]).write_bytes(b"corrupt")
    with pytest.raises(IntegrityError):
        transfer.transfer(manifest)
    assert not client.gets and not client.puts


def test_v1_and_bad_paths_cannot_be_transferred(tmp_path):
    _store, manifest, client, transfer = transferred(tmp_path)
    legacy = copy.deepcopy(manifest)
    legacy["schema_version"] = 1
    with pytest.raises(IntegrityError, match="v2"):
        transfer.transfer(legacy)
    with pytest.raises(IntegrityError):
        transfer.key("../outside")
    assert not client.gets


def test_upload_retry_exhaustion_and_partial_recovery(tmp_path):
    store, manifest, client, transfer = transferred(tmp_path)
    client.fail_key = "/raw/"
    client.failures = 5
    with pytest.raises(CloudError):
        transfer.transfer(manifest)
    batch = prepare_batch(store, manifest, "portfolio")
    state = parse_json(transfer._state_path(batch.batch_id).read_bytes())
    assert state["status"] == "pending" and state["attempts"][-1]["status"] == "failed"
    assert (transfer.bucket, transfer.receipt_key(batch.batch_id)) not in client.objects
    uploaded_before = set(client.puts)
    client.failures = 0
    transfer.transfer(manifest)
    assert all(client.puts.count(key) == 1 for key in uploaded_before)
    assert transfer.verified_batch(manifest).batch_id == batch.batch_id


def test_corrupted_upload_never_publishes_ready(tmp_path):
    store, manifest, client, transfer = transferred(tmp_path)
    client.corrupt_put = True
    with pytest.raises(IntegrityError, match="checksum"):
        transfer.transfer(manifest)
    batch = prepare_batch(store, manifest, "portfolio")
    assert (transfer.bucket, transfer.receipt_key(batch.batch_id)) not in client.objects
    assert parse_json(transfer._state_path(batch.batch_id).read_bytes())["status"] == "pending"


def test_ready_publication_interruption_recovers_without_new_uploads(tmp_path):
    store, manifest, client, transfer = transferred(tmp_path)
    client.interrupt_ready = True
    with pytest.raises(KeyboardInterrupt):
        transfer.transfer(manifest)
    puts = len(client.puts)
    report = transfer.transfer(manifest)
    assert len(client.puts) == puts and report["uploaded"] == 0
    journal = parse_json(transfer._state_path(report["batch_id"]).read_bytes())
    assert journal["attempts"][0]["status"] == "interrupted"
    assert journal["status"] == "success"


def test_pinned_identity_rejects_rewritten_valid_manifest(tmp_path):
    store, manifest, client, transfer = transferred(tmp_path)
    transfer.transfer(manifest)
    changed = copy.deepcopy(manifest)
    changed["counts"]["duplicates"] += 1
    changed["counts"]["retrieved"] += 1
    changed["manifest_sha256"] = manifest_digest(changed)
    (store.root / manifest["manifest"]).write_bytes(json_bytes(changed))
    puts = len(client.puts)
    with pytest.raises(IntegrityError, match="pinned"):
        transfer.transfer(changed)
    assert len(client.puts) == puts


def test_remote_corruption_and_missing_ready_block_warehouse_input(tmp_path):
    store, manifest, client, transfer = transferred(tmp_path)
    with pytest.raises(IntegrityError, match="ready"):
        transfer.verified_batch(manifest)
    transfer.transfer(manifest)
    raw_key = transfer.key(manifest["objects"][0]["object_key"])
    client.objects[transfer.bucket, raw_key] = b"corrupt"
    with pytest.raises(IntegrityError, match="checksum"):
        transfer.verified_batch(manifest)


def test_timeout_after_s3_write_recovers_via_conditional_conflict(tmp_path, monkeypatch):
    from cloud_doubles import ServiceError

    _store, manifest, client, transfer = transferred(tmp_path)
    original = client.put_object
    pending = [True]

    def write_then_timeout(**kwargs):
        result = original(**kwargs)
        if pending:
            pending.pop()
            raise ServiceError("RequestTimeout")
        return result

    monkeypatch.setattr(client, "put_object", write_then_timeout)
    assert transfer.transfer(manifest)["status"] == "success"
    assert len(client.puts) == len(set(client.puts))


def test_transient_upload_retries_use_bounded_backoff(tmp_path):
    _store, manifest, client, transfer = transferred(tmp_path)
    delays = []
    transfer.sleep = delays.append
    client.failures = 2
    assert transfer.transfer(manifest)["status"] == "success"
    assert len(delays) == 2
    assert 1 <= delays[0] <= 1.25 and 2 <= delays[1] <= 2.25


def test_missing_local_transfer_checkpoint_recovers_from_verified_remote_receipt(tmp_path):
    _store, manifest, client, transfer = transferred(tmp_path)
    first = transfer.transfer(manifest)
    transfer._state_path(first["batch_id"]).unlink()
    put_count = len(client.puts)
    replay = transfer.transfer(manifest)
    assert replay["batch_id"] == first["batch_id"] and replay["uploaded"] == 0
    assert len(client.puts) == put_count
