from ingestion.__main__ import main
from ingestion.pipeline import run_ingestion
from storage import cloud_cli
from storage.local import LocalStore
from cloud_doubles import MemoryS3, MemoryWarehouse
from test_local_ingestion import task


def test_cloud_cli_rejects_missing_configuration_without_network(tmp_path, monkeypatch, capsys):
    run_ingestion(LocalStore(tmp_path), [task()], mode="backfill")
    monkeypatch.delenv("FIN_S3_BUCKET", raising=False)
    assert main(["transfer", "--source", "fred", "--entity", "TEST", "--data-dir", str(tmp_path)]) == 1
    assert "FIN_S3_BUCKET" in capsys.readouterr().out


def test_cloud_cli_transfer_and_load_use_separate_commands(tmp_path, monkeypatch):
    run_ingestion(LocalStore(tmp_path), [task()], mode="backfill")
    client, db = MemoryS3(), MemoryWarehouse()
    monkeypatch.setenv("FIN_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("FIN_ARCHIVE_NAMESPACE", "portfolio")
    monkeypatch.setattr(cloud_cli, "_s3_client", lambda: client)
    monkeypatch.setattr(cloud_cli, "_snowflake_factory", lambda: (db.connect, "test-target"))
    args = ["--source", "fred", "--entity", "TEST", "--data-dir", str(tmp_path)]
    assert main(["transfer", *args]) == 0
    assert db.connects == 0
    assert main(["load", *args]) == 0
    assert len(db.tables["OPS.BATCH_LOAD"]) == 1


def test_missing_aws_credentials_does_not_use_instance_metadata(monkeypatch):
    import pytest
    from storage.transfer import CloudError

    for name in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(CloudError, match="AWS_PROFILE"):
        cloud_cli._s3_client()


def test_snowflake_factory_uses_json_results_and_separate_transaction_session(tmp_path, monkeypatch):
    import snowflake.connector

    key = tmp_path / "test-key.p8"
    key.write_text("synthetic key placeholder")
    values = {
        "SNOWFLAKE_ACCOUNT": "offline-account", "SNOWFLAKE_USER": "offline-user",
        "SNOWFLAKE_DATABASE": "OFFLINE_DB", "SNOWFLAKE_WAREHOUSE": "OFFLINE_WH",
        "SNOWFLAKE_ROLE": "OFFLINE_ROLE", "SNOWFLAKE_PRIVATE_KEY_FILE": str(key),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    captured = {}
    monkeypatch.setattr(snowflake.connector, "connect", lambda **kwargs: captured.update(kwargs))
    factory, target = cloud_cli._snowflake_factory()
    assert captured == {}
    factory()
    assert captured["session_parameters"]["PYTHON_CONNECTOR_QUERY_RESULT_FORMAT"] == "JSON"
    assert captured["autocommit"] is False and captured["paramstyle"] == "pyformat"
    assert "offline-account" in target and "OFFLINE_DB" in target
