import pytest
import json
from datetime import date

import requests

from ingestion.pipeline import run_ingestion
from ingestion.http import JsonClient
from scripts import validate_sources
from storage.local import LocalStore
from test_fred import metadata, observation, page, task as fred_task
from test_sec import CIK, ORIGINAL_FILING, facts, fact, submissions, task as sec_task


def test_numeric_profile_reports_quarantine_and_preserves_missing_zero():
    result = validate_sources.numeric_profile([
        {"value": "0"}, {"value": None}, {"value": "-12.125"},
        {"value": "0.0000000000001"}, {"value": "123456789012345678901234567890123456789"},
        {"dataset": "filings"},
    ])
    assert result == {
        "numeric_rows": 4, "max_integer_digits": 39, "max_fractional_digits": 13,
        "unsupported_number_38_12": 2, "null_values": 1,
    }


def test_fred_audit_compares_raw_records_and_prepares_cloud_inputs_without_clients(tmp_path, fake_http):
    client, _ = fake_http([metadata(), page(0, 1, observation("2024-01-01", "0.125"))])
    store = LocalStore(tmp_path)
    run_ingestion(store, [fred_task(client)], mode="backfill")
    manifest, = store.manifests("fred", "FEDFUNDS")
    report = validate_sources.inspect_batch(store, manifest)
    assert report["source_rows_compared"] == 1
    assert report["schema_version"] == 2 and len(report["batch_id"]) == 64
    assert report["numeric_profile"]["max_fractional_digits"] == 3
    assert report["loader_input"] == {"changes": 1, "snapshot_members": 0, "quarantined": 0}


def test_sec_audit_profiles_actual_indexed_fact_shape_and_snapshot_asof(tmp_path, fake_http):
    client, _ = fake_http([
        submissions(ORIGINAL_FILING), facts({"Revenues": {"USD": [fact(123)]}}),
    ])
    store = LocalStore(tmp_path)
    run_ingestion(store, [sec_task(client)], mode="backfill")
    manifest, = store.manifests("sec", CIK)
    report = validate_sources.inspect_batch(store, manifest)
    assert report["source_rows_compared"] == 2
    assert report["loader_input"]["snapshot_members"] == 2
    assert report["sec"]["tags"] == ["Revenues"]
    assert report["sec"]["period_classes"] == {"annual": 1}
    assert report["sec"]["historical_snapshot_matches"]


def test_missing_credentials_skip_live_operations_and_preserve_existing_output(tmp_path, monkeypatch):
    root = validate_sources.ROOT
    (tmp_path / "config").mkdir()
    (tmp_path / "config/source_scope.toml").write_bytes((root / "config/source_scope.toml").read_bytes())
    monkeypatch.setattr(validate_sources, "ROOT", tmp_path)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    output = tmp_path / ".local" / "audit"
    result = validate_sources.run_validation(output)
    assert result["http_responses"] == 0
    assert {item["status"] for item in result["sources"].values()} == {"configuration_required"}
    assert not (output / "archive").exists()
    before = (output / "summary.json").read_bytes()
    with pytest.raises(FileExistsError):
        validate_sources.run_validation(output)
    assert (output / "summary.json").read_bytes() == before


def test_validation_http_evidence_redacts_request_key_and_checks_replay(tmp_path, monkeypatch):
    root = validate_sources.ROOT
    (tmp_path / "config").mkdir()
    (tmp_path / "config/source_scope.toml").write_bytes((root / "config/source_scope.toml").read_bytes())
    monkeypatch.setattr(validate_sources, "ROOT", tmp_path)
    sentinel = "synthetic-key-must-not-appear-in-evidence"
    monkeypatch.setenv("FRED_API_KEY", sentinel)
    monkeypatch.setattr(
        validate_sources, "JsonClient",
        lambda session, rate: JsonClient(session, rate=rate, sleep=lambda _seconds: None),
    )

    def get(session, url, *, params, headers, **_kwargs):
        if url.endswith("/series"):
            payload = {"seriess": [{"id": "DGS10", "frequency": "Daily", "units": "Percent"}]}
        else:
            payload = {"offset": 0, "count": 2, "observations": [
                {
                    "date": day, "value": value, "realtime_start": date.today().isoformat(),
                    "realtime_end": date.today().isoformat(),
                }
                for day, value in (("2024-01-01", "."), ("2024-01-02", "3.875"))
            ]}
        response = requests.Response()
        response._content = json.dumps(payload).encode()
        response.status_code = 200
        response.headers["Content-Type"] = "application/json"
        response.request = requests.Request("GET", url, params=params, headers=headers).prepare()
        response.url = response.request.url
        assert sentinel in response.url
        for hook in session.hooks["response"]:
            hook(response)
        return response

    monkeypatch.setattr(requests.Session, "get", get)
    output = tmp_path / ".local" / "mocked-validation"
    report = validate_sources.run_validation(output, "fred")
    assert report["sources"]["fred"]["status"] == "validated"
    assert report["sources"]["fred"]["repeat_written"] == 0
    assert report["http_responses"] == 4
    assert report["sources"]["fred"]["batches"][0]["numeric_profile"]["null_values"] == 1
    outcomes = json.loads((output / "http-outcomes.json").read_bytes())
    assert {row["status_code"] for row in outcomes} == {200}
    assert all("?" not in row["path"] for row in outcomes)
    for filename in ("summary.json", "http-outcomes.json"):
        assert sentinel not in (output / filename).read_text()
