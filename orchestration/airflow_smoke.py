"""Exercise discovery, task retries and publication inside the offline Airflow image."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from airflow.models.dagbag import DagBag


TASKS = ("ingest_fixture", "validate_fixture", "dbt_build")
TASK_WRAPPER = """
import os
import sys
from pathlib import Path

stage, work = sys.argv[-2:]
if stage == "validate":
    marker = Path(work) / "smoke-validation-failed"
    if os.environ["FDEP_SMOKE_FAILURE"] == "persistent" or not marker.exists():
        marker.write_text("validation failed")
        sys.exit("Injected validation failure")
python = os.environ["FDEP_SMOKE_REAL_PYTHON"]
os.execv(python, [python, *sys.argv[1:]])
"""
CHECK_PUBLICATION = """
import sys
import duckdb

with duckdb.connect(sys.argv[1], read_only=True) as db:
    counts = db.execute('''
        select
            (select count(*) from fdep_staging.stg_batches),
            (select count(distinct series_id) from fdep_analytics.fact_economic_observations),
            (select count(*) from fdep_analytics.sec_selected_snapshots)
    ''').fetchone()
    assert counts == (21, 6, 12), counts
    print(f"Published batches, distinct FRED series, selected SEC snapshots: {counts}")
"""


def main() -> None:
    bag = DagBag(include_examples=False)
    assert not bag.import_errors, bag.import_errors
    dag = bag.dags["financial_local"]
    print(f"Discovered {dag.dag_id}", flush=True)
    assert set(dag.task_ids) == set(TASKS), dag.task_ids
    for index, task_id in enumerate(TASKS):
        expected = {TASKS[index - 1]} if index else set()
        assert dag.get_task(task_id).upstream_task_ids == expected, task_id
        assert dag.get_task(task_id).retries == 1, task_id

    python = os.environ["FDEP_TASK_PYTHON"]
    base = Path(os.environ["FDEP_AIRFLOW_WORK_DIR"])
    base.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=base) as directory:
        work = Path(directory)
        wrapper = work / "task-python"
        wrapper.write_text(f"#!{sys.executable}\n{TASK_WRAPPER}", encoding="utf-8")
        wrapper.chmod(0o700)
        os.environ.update(FDEP_SMOKE_REAL_PYTHON=python, FDEP_TASK_PYTHON=str(wrapper),
                          FDEP_AIRFLOW_WORK_DIR=str(work))
        for failure in ("transient", "persistent"):
            os.environ["FDEP_SMOKE_FAILURE"] = failure
            result = dag.test()
            instances = {task.task_id: task for task in result.get_task_instances()}
            states = {key: (instances[key].state, instances[key].try_number) for key in TASKS}
            publication = work / hashlib.sha256(result.run_id.encode()).hexdigest() / "analytics.duckdb"
            assert states["ingest_fixture"] == ("success", 1), states
            if failure == "transient":
                assert result.state == "success", result.state
                assert states["validate_fixture"] == ("success", 2), states
                assert states["dbt_build"] == ("success", 1), states
                assert instances["ingest_fixture"].end_date <= instances["validate_fixture"].start_date
                assert instances["validate_fixture"].end_date <= instances["dbt_build"].start_date
                subprocess.run([python, "-c", CHECK_PUBLICATION, str(publication)], check=True, timeout=30)
            else:
                assert result.state == "failed", result.state
                assert states["validate_fixture"] == ("failed", 2), states
                assert states["dbt_build"] == ("upstream_failed", 0), states
                assert not publication.exists(), publication
            print(f"{failure} validation failure: {result.state} {states}", flush=True)


if __name__ == "__main__":
    main()
