"""Manual, credential-free fixture run for the financial platform."""

import hashlib
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.sdk import dag, get_current_context, task


ROOT = Path(__file__).resolve().parents[2]


@dag(
    dag_id="financial_local",
    schedule=None,
    start_date=pendulum.datetime(2024, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 1,
        "retry_delay": timedelta(seconds=15),
        "execution_timeout": timedelta(minutes=3),
    },
    tags=["financial", "offline"],
)
def financial_local():
    @task(do_xcom_push=False)
    def run_stage(stage: str) -> None:
        run_id = get_current_context()["run_id"]
        run_key = hashlib.sha256(run_id.encode()).hexdigest()
        base = Path(os.environ.get("FDEP_AIRFLOW_WORK_DIR", ROOT / ".local/phase5/airflow-runs"))
        python = os.environ.get("FDEP_TASK_PYTHON", sys.executable)
        subprocess.run(
            [python, "-m", "orchestration.local", stage, str(base / run_key)],
            cwd=ROOT, check=True, timeout=150,
        )

    ingest = run_stage.override(task_id="ingest_fixture")("ingest")
    validate = run_stage.override(task_id="validate_fixture")("validate")
    transform = run_stage.override(task_id="dbt_build")("transform")
    ingest >> validate >> transform


dag = financial_local()

if __name__ == "__main__":
    result = dag.test()
    if result.state != "success":
        raise SystemExit(1)
