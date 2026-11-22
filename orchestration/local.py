"""Run the deterministic Phase 5 stages from Airflow or the command line."""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from filelock import FileLock

from scripts.phase4_fixture import ROOT, create_fixture, source_scope

FIXTURE = "fixture.duckdb"


def ingest(work: Path) -> None:
    """Publish a complete fixture database, reusing it when the task is retried."""
    raw = work / FIXTURE
    if not raw.exists():
        with TemporaryDirectory(dir=work) as directory:
            candidate = Path(directory) / raw.name
            create_fixture(candidate)
            candidate.replace(raw)


def validate(work: Path) -> int:
    import duckdb

    scope = source_scope()
    expected = {(source, entity) for source, entities in (
        ("fred", scope["fred"]["series"]),
        ("sec", scope["sec"]["companies"].values()),
    ) for entity in entities}
    with closing(duckdb.connect(str(work / FIXTURE), read_only=True)) as db:
        rows = db.execute("""
            select batch_id, manifest_text ->> 'source', manifest_text ->> 'entity'
            from ops.batch_load
        """).fetchall()
    if (
        {(source, entity) for _, source, entity in rows} != expected
        or len(rows) != len(expected) + 3
        or len({batch_id for batch_id, _, _ in rows}) != len(rows)
    ):
        raise ValueError("Fixture batch coverage or identity failed validation")
    return len(rows)


def transform(work: Path) -> None:
    build_analytics(work / FIXTURE, work / "analytics.duckdb")


def build_analytics(raw: Path, output: Path) -> None:
    """Build on a separate database and publish it only after dbt tests pass."""
    with TemporaryDirectory(dir=output.parent) as directory:
        attempt = Path(directory)
        # DuckDB views can bind the catalog name derived from the file stem.
        candidate = attempt / output.name
        shutil.copyfile(raw, candidate)
        shutil.copyfile(ROOT / "dbt/profiles.example.yml", attempt / "profiles.yml")
        # Keep inherited dbt configuration from overriding the local smoke target.
        env = {key: value for key, value in os.environ.items()
               if not key.upper().startswith(("DBT_", "FDEP_"))}
        env.update(
            FDEP_DUCKDB_PATH=candidate.as_posix(),
            DBT_SEND_ANONYMOUS_USAGE_STATS="false",
            DBT_TARGET_PATH=str(attempt / "target"),
            DBT_LOG_PATH=str(attempt / "logs"),
        )
        subprocess.run(
            [sys.executable, "-m", "dbt.cli.main", "build",
             "--project-dir", str(ROOT / "dbt"), "--profiles-dir", str(attempt),
             "--target", "local"],
            cwd=ROOT, env=env, check=True, timeout=120,
        )
        candidate.replace(output)


def run(stage: str, work: Path) -> None:
    work = work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    stages = {"ingest": ingest, "validate": validate, "transform": transform}
    selected = tuple(stages) if stage == "smoke" else (stage,)
    with FileLock(work / "pipeline.lock", timeout=5):
        for name in selected:
            started = monotonic()
            event = {"run_id": work.name, "stage": name}
            try:
                count = stages[name](work)
            except Exception:
                logging.error(json.dumps(dict(event, status="failed", duration_s=monotonic() - started)))
                raise
            logging.info(json.dumps(dict(event, status="success", batches=count, duration_s=monotonic() - started)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("ingest", "validate", "transform", "smoke"))
    parser.add_argument("work", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run(args.stage, args.work)
