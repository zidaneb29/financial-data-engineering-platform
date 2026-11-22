import json
from datetime import date

import pytest
import requests
from filelock import Timeout

from ingestion.__main__ import main
from ingestion.models import Record
from ingestion.http import decode_json
from ingestion.pipeline import IngestionTask, run_ingestion
from storage import local
from conftest import response


TODAY = date(2024, 3, 1)


def task(name="TEST", value="1"):
    def fetch(batch):
        metadata_params = {
            "series_id": name, "file_type": "json",
            "realtime_start": TODAY.isoformat(), "realtime_end": TODAY.isoformat(),
        }
        metadata = decode_json(json.dumps({"seriess": [{"id": name}]}).encode())
        metadata_key = batch.archive("series", metadata, metadata_params)
        observation_params = {
            **metadata_params, "observation_start": TODAY.isoformat(), "observation_end": TODAY.isoformat(),
            "units": "lin", "order_by": "observation_date", "sort_order": "asc", "limit": 1, "offset": 0,
        }
        source = decode_json(json.dumps({"observations": [{"date": TODAY.isoformat(), "value": value}]}).encode())
        object_key = batch.archive("observations", source, observation_params)
        batch.metadata.update(snapshot_date=TODAY.isoformat(), series_metadata_key=metadata_key)
        return [Record("observations", (TODAY.isoformat(),), {
            "series_id": name, "observation_date": TODAY.isoformat(), "value": value,
            "units": "Percent", "frequency": "monthly", "is_missing": False, "seasonal_adjustment": None,
        }, {
            "object_key": object_key, "source_row": 0, "snapshot_date": TODAY.isoformat(),
            "realtime_start": TODAY.isoformat(), "realtime_end": TODAY.isoformat(),
            "series_metadata_key": metadata_key,
        })]
    return IngestionTask(
        "fred", name, lambda _store: (TODAY, TODAY),
        fetch,
    )


def test_atomic_replace_failure_preserves_previously_published_file(tmp_path, monkeypatch):
    target = tmp_path / "dataset.json"
    local.atomic_write(target, b"original")

    def fail_replace(*_args):
        raise OSError("injected replace failure")

    monkeypatch.setattr(local.os, "replace", fail_replace)
    with pytest.raises(OSError):
        local.atomic_write(target, b"updated")
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_retries_a_transient_windows_sharing_error(tmp_path, monkeypatch):
    target = tmp_path / "dataset.json"
    local.atomic_write(target, b"original")
    replace = local.os.replace
    delays = []
    attempts = []

    def temporarily_locked(source, destination):
        attempts.append(source)
        if len(attempts) == 1:
            error = PermissionError("injected sharing violation")
            error.winerror = 32
            raise error
        replace(source, destination)

    monkeypatch.setattr(local.os, "replace", temporarily_locked)
    monkeypatch.setattr(local, "sleep", delays.append)
    local.atomic_write(target, b"updated")
    assert len(attempts) == 2 and delays == [0.05]
    assert target.read_bytes() == b"updated"


def test_uncommitted_normalized_write_is_invisible_and_recovers(tmp_path, monkeypatch):
    store = local.LocalStore(tmp_path)
    run_ingestion(store, [task()], mode="backfill")
    real_write = local.atomic_write

    def interrupted_write(path, data):
        if path.parent.name == "TEST" and "batches" in path.parts:
            raise KeyboardInterrupt
        real_write(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(local, "atomic_write", interrupted_write)
        with pytest.raises(KeyboardInterrupt):
            run_ingestion(store, [task(value="2"), task("LATER")], mode="incremental")
    assert len(list(tmp_path.glob("processed/fred/TEST/*/*.jsonl"))) == 2
    assert [row["value"] for row in store.rows(store.manifests("fred", "TEST"))] == ["1"]
    run = run_ingestion(store, [task(value="2")], mode="incremental")
    assert run["counts"]["revised"] == 1
    assert [row["value"] for row in store.rows(store.manifests("fred", "TEST"))] == ["1", "2"]
    journals = [json.loads(path.read_bytes()) for path in tmp_path.glob("metadata/runs/*.json")]
    interrupted, = [item for item in journals if item["status"] == "interrupted"]
    assert [entity["status"] for entity in interrupted["entities"]] == ["interrupted", "skipped"]


def test_recovery_recognizes_manifest_committed_before_run_summary(tmp_path, monkeypatch):
    store = local.LocalStore(tmp_path)
    commit = store.commit

    def interrupt_after_commit(*args):
        commit(*args)
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(store, "commit", interrupt_after_commit)
        with pytest.raises(KeyboardInterrupt):
            run_ingestion(store, [task()], mode="incremental")
    run = run_ingestion(store, [task()], mode="incremental")
    assert run["counts"]["duplicates"] == 1
    journals = [json.loads(path.read_bytes()) for path in tmp_path.glob("metadata/runs/*.json")]
    recovered, = [item for item in journals if "recovered_at" in item]
    assert recovered["status"] == "success"
    assert recovered["entities"][0]["written"] == 1


def test_local_writer_lock_rejects_an_overlapping_run(tmp_path):
    store = local.LocalStore(tmp_path)
    with store.lock(), pytest.raises(Timeout):
        run_ingestion(store, [task()], mode="incremental")


def test_cli_runs_sec_when_fred_configuration_is_missing(tmp_path, monkeypatch):
    agent = "Local Test monitored@example.test"
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setenv("SEC_USER_AGENT", agent)
    monkeypatch.setenv("FIN_DATA_DIR", str(tmp_path))
    calls = []

    def get(_session, url, **kwargs):
        calls.append(url)
        assert kwargs["headers"]["User-Agent"] == agent
        if "/submissions/" in url:
            recent = {
                name: [] for name in ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")
            }
            return response({"cik": "0000789019", "filings": {"recent": recent, "files": []}})
        return response({"cik": 789019, "facts": {}})

    monkeypatch.setattr(requests.Session, "get", get)
    assert main(["all", "--fred-series", "FEDFUNDS", "--sec-issuer", "msft", "--end", "2024-01-01"]) == 1
    assert len(calls) == 2
    path, = tmp_path.glob("metadata/runs/*.json")
    run = json.loads(path.read_bytes())
    assert run["status"] == "partial"
    assert run["entities"][0]["error_code"] == "missing_configuration"
    assert run["entities"][1]["status"] == "success"


def test_cli_rejects_invalid_scope_before_writing(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["fred", "--fred-series", "UNKNOWN", "--data-dir", str(tmp_path)])
    assert exc.value.code == 2
    assert "Unknown configured entity" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())
