import copy
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from ingestion.http import decode_json
from ingestion.pipeline import run_ingestion
from storage.local import Batch, LocalStore, atomic_write, json_bytes
from storage.manifest import IntegrityError, digest, manifest_digest, parse_json
from test_local_ingestion import task


def committed(tmp_path):
    store = LocalStore(tmp_path)
    run = run_ingestion(store, [task()], mode="backfill")
    assert run["status"] == "success"
    return store, store.manifests("fred", "TEST")[0]


def save_manifest(store, manifest, *, resign=True):
    if resign:
        manifest["manifest_sha256"] = manifest_digest(manifest)
    atomic_write(store.root / manifest["manifest"], json_bytes(manifest))


def test_normalized_file_hash_count_and_row_inventory(tmp_path):
    store, manifest = committed(tmp_path)
    assert manifest["schema_version"] == 2
    path = store.root / manifest["normalized"]["observations"]
    info = manifest["normalized_files"]["observations"]
    assert info == {"sha256": digest(path.read_bytes()), "byte_size": path.stat().st_size, "row_count": 1}
    row, = store.rows([manifest])
    assert row["business_fields"] == sorted(row["business_fields"])
    assert row["value"] == "1"


@pytest.mark.parametrize("body", [b"", b'{"value":"2"}\n', b'{"truncated":'])
def test_corrupted_normalized_file_blocks_discovery_rows_and_coverage(tmp_path, body):
    store, manifest = committed(tmp_path)
    (store.root / manifest["normalized"]["observations"]).write_bytes(body)
    for read in (
        lambda: store.manifests("fred", "TEST"),
        lambda: list(store.rows([manifest])),
        lambda: store.coverage("fred", "TEST", date(2024, 3, 1)),
    ):
        with pytest.raises(IntegrityError, match="checksum"):
            read()


def test_manifest_edit_and_in_memory_tampering_are_rejected(tmp_path):
    store, manifest = committed(tmp_path)
    changed = copy.deepcopy(manifest)
    changed["counts"]["duplicates"] = 1
    changed["counts"]["retrieved"] += 1
    with pytest.raises(IntegrityError):
        list(store.rows([changed]))
    save_manifest(store, changed, resign=False)
    with pytest.raises(IntegrityError, match="checksum"):
        store.manifests("fred", "TEST")


@pytest.mark.parametrize("reference", [
    "../outside.jsonl", "processed/fred/TEST/../outside.jsonl",
    "C:/outside.jsonl", "/outside.jsonl", "processed\\fred\\TEST\\outside.jsonl",
    "processed//fred/TEST/output.jsonl", "raw/fred/TEST/observations/output.jsonl",
    "processed/fred/OTHER/run/observations.jsonl", "processed/fred/TEST/run/observations.jsonl:stream",
])
def test_invalid_normalized_locations_rejected_even_with_recomputed_manifest_hash(tmp_path, reference):
    store, manifest = committed(tmp_path)
    manifest["normalized"]["observations"] = reference
    save_manifest(store, manifest)
    with pytest.raises(IntegrityError):
        store.manifests("fred", "TEST")


@pytest.mark.parametrize("mutation", [
    lambda batch: batch.update(schema_version=True),
    lambda batch: batch.update(status="failed"),
    lambda batch: batch.update(extra_field="unexpected"),
    lambda batch: batch["normalized_files"]["observations"].update(row_count=2),
    lambda batch: batch["normalized_files"]["observations"].update(byte_size=True),
    lambda batch: batch["objects"][0].update(endpoint="companyfacts"),
    lambda batch: batch["objects"][0]["params"].update(api_key="synthetic-secret"),
    lambda batch: batch.update(objects=[]),
    lambda batch: batch.update(start="2025-01-01"),
    lambda batch: batch.update(run_id="../invalid"),
])
def test_invalid_manifest_schemas_are_rejected(tmp_path, mutation):
    store, manifest = committed(tmp_path)
    mutation(manifest)
    save_manifest(store, manifest)
    with pytest.raises(IntegrityError):
        store.manifests("fred", "TEST")


def test_redirected_storage_directory_is_rejected(tmp_path):
    store, manifest = committed(tmp_path)
    from storage import manifest as schema

    original = Path.resolve
    raw = store.root / "raw"

    def redirected(path, *args, **kwargs):
        resolved = original(path, *args, **kwargs)
        if raw in path.parents:
            return store.root.parent / "redirected" / path.name
        return resolved

    # Exercise the resolution boundary portably without Windows symlink privileges.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "resolve", redirected)
        with pytest.raises(IntegrityError, match="redirected"):
            schema.safe_path(store.root, manifest["objects"][0]["object_key"])


def test_raw_corruption_is_rejected_on_read_and_content_addressed_reuse(tmp_path):
    store, manifest = committed(tmp_path)
    reference = manifest["objects"][0]
    body = store.read_object(reference)
    path = store.root / reference["object_key"]
    path.write_bytes(b"{}")
    with pytest.raises(IntegrityError, match="checksum"):
        store.manifests("fred", "TEST")
    batch = Batch(store, "fred", "TEST", uuid4().hex, date(2024, 3, 1), date(2024, 3, 1))
    with pytest.raises(IntegrityError, match="checksum"):
        batch.archive("series", decode_json(body), reference["params"])
    assert path.read_bytes() == b"{}" and batch.objects == []


def test_missing_referenced_file_and_duplicate_json_fields_are_rejected(tmp_path):
    store, manifest = committed(tmp_path)
    (store.root / manifest["normalized"]["observations"]).unlink()
    with pytest.raises(OSError):
        store.manifests("fred", "TEST")
    path = store.root / manifest["manifest"]
    path.write_bytes(b'{"schema_version":2,"schema_version":1}')
    with pytest.raises(IntegrityError, match="Duplicate"):
        store.manifests("fred", "TEST")


def test_sequence_reservations_survive_deletion_of_highest_manifest(tmp_path):
    store, first = committed(tmp_path)
    run_ingestion(store, [task(value="2")], mode="incremental")
    first, second = store.manifests("fred", "TEST")
    preserved = (store.root / first["manifest"]).read_bytes()
    (store.root / second["manifest"]).unlink()
    run = run_ingestion(store, [task(value="3")], mode="incremental")
    assert run["status"] == "success"
    remaining = store.manifests("fred", "TEST")
    assert [Path(batch["manifest"]).stem for batch in remaining] == ["000000000001", "000000000003"]
    assert (store.root / first["manifest"]).read_bytes() == preserved


def test_reserved_sequence_is_consumed_when_publication_is_interrupted(tmp_path, monkeypatch):
    store, first = committed(tmp_path)
    from storage import local

    real_write = local.atomic_write

    def stop_manifest(path, body):
        if path.parent.name == "TEST" and "batches" in path.parts:
            raise KeyboardInterrupt
        real_write(path, body)

    with monkeypatch.context() as patch:
        patch.setattr(local, "atomic_write", stop_manifest)
        with pytest.raises(KeyboardInterrupt):
            run_ingestion(store, [task(value="2")], mode="incremental")
    assert len(store.manifests("fred", "TEST")) == 1
    run_ingestion(store, [task(value="2")], mode="incremental")
    latest = store.manifests("fred", "TEST")[-1]
    assert latest["manifest"].endswith("000000000003.json")
    assert [row["value"] for row in store.rows([first, latest])] == ["1", "2"]


def test_legitimate_v1_batch_remains_readable_and_new_commits_use_v2(tmp_path):
    store, manifest = committed(tmp_path)
    normalized_path = store.root / manifest["normalized"]["observations"]
    row = parse_json(normalized_path.read_bytes())
    row.pop("business_fields")
    atomic_write(normalized_path, json_bytes(row))
    manifest["schema_version"] = 1
    manifest.pop("normalized_files")
    manifest.pop("manifest_sha256")
    atomic_write(store.root / manifest["manifest"], json_bytes(manifest))
    assert list(store.rows(store.manifests("fred", "TEST")))[0]["value"] == "1"
    run = run_ingestion(store, [task()], mode="incremental")
    assert run["counts"]["duplicates"] == 1
    assert store.manifests("fred", "TEST")[-1]["schema_version"] == 2
    row["value"] = "9"
    atomic_write(normalized_path, json_bytes(row))
    with pytest.raises(IntegrityError, match="fingerprint"):
        store.manifests("fred", "TEST")


def test_legacy_sequence_bootstraps_from_journal_when_manifest_is_deleted(tmp_path):
    store, manifest = committed(tmp_path)
    (store.root / manifest["manifest"]).unlink()
    (store.root / "metadata/sequences/fred/TEST.json").unlink()
    run_ingestion(store, [task()], mode="incremental")
    assert store.manifests("fred", "TEST")[0]["manifest"].endswith("000000000002.json")


def test_validated_replay_has_stable_transfer_identity_and_retains_reversion_events(tmp_path):
    store, first = committed(tmp_path)
    for value in ("2", "1", "1"):
        run_ingestion(store, [task(value=value)], mode="incremental")
    batches = store.manifests("fred", "TEST")
    events = [
        (batch["source"], batch["entity"], batch["run_id"], ordinal)
        for batch in batches for ordinal, _row in enumerate(store.validate_batch(batch))
    ]
    assert len(events) == len(set(events)) == 3
    assert [row["value"] for row in store.rows(batches)] == ["1", "2", "1"]
    assert store.validate_batch(batches[-1]) == []
    assert manifest_digest(first) == first["manifest_sha256"]


@pytest.mark.parametrize("mutation", [
    lambda row: row.update(business_fields=[{}]),
    lambda row: row.update(comparison_key=[{}]),
    lambda row: row.update(key=["wrong-date"]),
    lambda row: row.update(source="sec"),
    lambda row: row.update(object_key="raw/fred/OTHER/observations/unrelated.json"),
    lambda row: row.update(ingestion_timestamp="2030-01-01T00:00:00+00:00"),
])
def test_checksums_do_not_replace_normalized_schema_validation(tmp_path, mutation):
    store, manifest = committed(tmp_path)
    path = store.root / manifest["normalized"]["observations"]
    row = parse_json(path.read_bytes())
    mutation(row)
    body = json_bytes(row)
    atomic_write(path, body)
    manifest["normalized_files"]["observations"].update(sha256=digest(body), byte_size=len(body))
    save_manifest(store, manifest)
    with pytest.raises(IntegrityError):
        store.manifests("fred", "TEST")


def test_interrupted_journal_cannot_promote_a_corrupted_batch(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)
    commit = store.commit

    def interrupt_after_commit(*args):
        manifest = commit(*args)
        (store.root / manifest["normalized"]["observations"]).write_bytes(b"corrupt")
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(store, "commit", interrupt_after_commit)
        with pytest.raises(KeyboardInterrupt):
            run_ingestion(store, [task()], mode="backfill")
    with pytest.raises(IntegrityError, match="checksum"):
        store.recover_runs()
    path, = (store.root / "metadata/runs").glob("*.json")
    assert parse_json(path.read_bytes())["status"] == "running"
