import runpy
import subprocess
from pathlib import Path

import pytest


def test_local_retry_and_atomic_dbt_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    duckdb = pytest.importorskip("duckdb")
    pytest.importorskip("dbt.adapters.duckdb")
    from orchestration import local

    # A stale inherited dbt option must never select another profile or target.
    monkeypatch.setenv("DBT_PROFILES_DIR", str(tmp_path / "untrusted"))
    monkeypatch.setenv("DBT_TARGET", "snowflake")
    local.run("smoke", tmp_path)
    raw = tmp_path / local.FIXTURE
    published = tmp_path / "analytics.duckdb"
    original = raw.read_bytes()
    local.run("ingest", tmp_path)
    assert raw.read_bytes() == original
    with duckdb.connect(str(published), read_only=True) as db:
        assert db.execute("""
            select count(distinct series_id) from fdep_analytics.fact_economic_observations
        """).fetchone() == (6,)

    output = published.read_bytes()

    def fail(command: list[str], **kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(local.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        local.run("transform", tmp_path)
    assert published.read_bytes() == output


def test_failed_ingest_can_retry_and_failed_validation_blocks_dbt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    duckdb = pytest.importorskip("duckdb")
    from orchestration import local

    def fail(path: Path) -> None:
        path.write_bytes(b"partial")
        raise OSError("interrupted fixture generation")

    with monkeypatch.context() as patch:
        patch.setattr(local, "create_fixture", fail)
        with pytest.raises(OSError):
            local.run("ingest", tmp_path)
    fixture = tmp_path / local.FIXTURE
    assert not fixture.exists()
    local.run("ingest", tmp_path)
    assert local.validate(tmp_path) == 21
    with duckdb.connect(str(fixture)) as db:
        db.execute("delete from ops.batch_load")
    with pytest.raises(ValueError, match="batch coverage"):
        local.run("smoke", tmp_path)
    assert not (tmp_path / "analytics.duckdb").exists()


def test_airflow_dag_dependencies() -> None:
    pytest.importorskip("airflow.sdk")
    path = Path(__file__).resolve().parents[1] / "orchestration/dags/financial_local.py"
    dag = runpy.run_path(str(path))["dag"]
    assert not dag.timetable.can_be_scheduled
    assert not dag.catchup
    assert dag.max_active_runs == 1
    assert set(dag.task_ids) == {"ingest_fixture", "validate_fixture", "dbt_build"}
    assert dag.get_task("validate_fixture").upstream_task_ids == {"ingest_fixture"}
    assert dag.get_task("dbt_build").upstream_task_ids == {"validate_fixture"}
    for task in dag.tasks:
        assert task.retries == 1
        assert task.trigger_rule == "all_success"
