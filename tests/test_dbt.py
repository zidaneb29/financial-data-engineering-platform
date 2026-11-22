"""Credential-free transformation regressions, enabled by requirements-dbt.txt."""

import csv
import os
import shutil
import subprocess
import sys
import tomllib
from decimal import Decimal
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_dbt_scope_matches_ingestion() -> None:
    with (ROOT / "config/source_scope.toml").open("rb") as stream:
        scope = tomllib.load(stream)
    with (ROOT / "dbt/seeds/series_scope.csv").open(newline="") as stream:
        assert {r["series_id"]: r["cadence"] for r in csv.DictReader(stream)} == scope["fred"]["series"]
    with (ROOT / "dbt/seeds/issuer_scope.csv").open(newline="") as stream:
        assert {r["ticker"]: r["cik"] for r in csv.DictReader(stream)} == scope["sec"]["companies"]


def test_dbt_build_and_point_in_time(tmp_path: Path) -> None:
    duckdb = pytest.importorskip("duckdb")
    pytest.importorskip("dbt.cli.main")
    pytest.importorskip("dbt.adapters.duckdb")
    from scripts.phase4_fixture import EXACT, create_fixture, load_batch, observation

    path = tmp_path / "fixture.duckdb"
    create_fixture(path)
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    shutil.copyfile(ROOT / "dbt/profiles.example.yml", profiles / "profiles.yml")
    env = {**os.environ, "FDEP_DUCKDB_PATH": str(path), "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
           "DBT_TARGET_PATH": str(tmp_path / "target"), "DBT_LOG_PATH": str(tmp_path / "logs")}

    def build(*args: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "dbt.cli.main", "build", "--project-dir", str(ROOT / "dbt"),
             "--profiles-dir", str(profiles), "--target", "local", *args],
            env=env, cwd=ROOT, capture_output=True, text=True, timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Done. PASS=" in result.stdout

    econ = "fdep_analytics.fact_economic_observations"
    financials = "fdep_analytics.fact_company_financials"
    candidates = "fdep_analytics.sec_financial_candidates"
    build()
    with duckdb.connect(str(path)) as db:
        assert db.execute(f"select count(distinct series_id) from {econ}").fetchone() == (6,)
        assert db.execute("select count(*) from fdep_analytics.sec_selected_snapshots").fetchone() == (12,)
        assert db.execute(f"""
            select value_text, value_number, is_missing, is_quarantined
            from {econ} where series_id = 'DGS10' order by observation_date
        """).fetchall() == [
            ("4.25", Decimal("4.25"), False, False),
            (None, None, True, False),
            ("0.0000000000001", None, False, True),
        ]
        rows = db.execute(f"""
            select tag, period_class, value_number, is_amendment, primary_document,
                acceptance_datetime_text, accession_number
            from {financials} where ticker = 'MSFT' order by tag, period_class
        """).fetchall()
        assert rows == [
            ("Assets", "instant", Decimal("150"), True, "report.htm",
             "2024-02-03T20:00:00Z", "0000000000-24-000002"),
            ("NetIncomeLoss", "year_to_date", Decimal("9"), False, "report.htm",
             "2024-01-29T20:00:00Z", "0000000000-24-000003"),
            ("Revenues", "annual", Decimal(EXACT), True, "report.htm",
             "2024-02-03T20:00:00Z", "0000000000-24-000002"),
            ("Revenues", "quarter", Decimal("110"), True, "report.htm",
             "2024-02-03T20:00:00Z", "0000000000-24-000002"),
        ]
        assert db.execute(f"""
            select value_text from {candidates} where ticker = 'MSFT' and tag = 'SalesRevenueNet'
            order by value_text
        """).fetchall() == [("91",), ("92",), ("93",)]
        assert db.execute(f"select count(*) from {financials} where ticker = 'CVX'").fetchone() == (0,)
        db.begin()
        load_batch(db, "fred", "DGS10", 3, "2024-02-02T08:00:00Z", [
            observation("DGS10", "2024-02-02", "99"),
        ], committed=False)
        assert db.execute(f"""
            select value_text from {econ} where series_id = 'DGS10' and observation_date = '2023-01-01'
        """).fetchone() == ("4.25",)
        db.rollback()

    build("--vars", '{"observed_through_utc":"2024-02-01T12:00:00Z",'
          '"fred_snapshot_through":"2024-02-01","sec_filed_through":"2024-01-20"}')
    with duckdb.connect(str(path)) as db:
        assert db.execute(f"""
            select value_number from {econ} where series_id = 'DGS10'
        """).fetchall() == [(Decimal(EXACT),)]
        assert db.execute(f"""
            select tag, value_text from {financials} where ticker = 'MSFT' order by tag
        """).fetchall() == [("OperatingIncomeLoss", "17"), ("Revenues", "100"), ("SalesRevenueNet", "91")]
        assert db.execute(f"select count(*) from {financials} where ticker = 'CVX'").fetchone() == (3,)

    build("--vars", '{"sec_filed_through":"2024-01-29","fred_snapshot_through":"2024-01-31"}')
    with duckdb.connect(str(path)) as db:
        assert db.execute(f"select count(*) from {econ}").fetchone() == (0,)
        assert db.execute(f"""
            select tag, value_text from {financials} where ticker = 'MSFT' order by tag
        """).fetchall() == [("NetIncomeLoss", "9"), ("Revenues", "100"), ("SalesRevenueNet", "91")]

