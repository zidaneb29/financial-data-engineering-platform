"""Offline checks of archive verification and safe local publication."""

from decimal import Decimal
from pathlib import Path

import pytest

from ingestion.pipeline import run_ingestion
from storage.local import LocalStore
from storage.manifest import IntegrityError
from test_local_ingestion import TODAY, task


def test_partial_archive_rebuild_and_full_coverage_guard(tmp_path: Path) -> None:
    duckdb = pytest.importorskip("duckdb")
    pytest.importorskip("dbt.adapters.duckdb")
    from scripts.build_history import publish_history

    archive = LocalStore(tmp_path / "archive")
    exact = "12345678901234567890123456.123456789012"
    for _ in range(2):
        run_ingestion(archive, [task("FEDFUNDS", exact)], mode="backfill")
    output = tmp_path / "published-history.duckdb"
    publish_history(archive.root, output, None)
    prior = output.read_bytes()
    with duckdb.connect(str(output), read_only=True) as db:
        assert db.sql("select value_number, value_text from fdep_analytics.fact_economic_observations").fetchone() == (
            Decimal(exact), exact,
        )
        assert db.sql("select count(*) from raw.source_object").fetchone() == (2,)
        assert db.sql("select count(*) from raw.batch_object").fetchone() == (4,)
    with pytest.raises(IntegrityError, match="Missing archive coverage"):
        publish_history(archive.root, output, (TODAY.isoformat(), TODAY.isoformat()))
    assert output.read_bytes() == prior
