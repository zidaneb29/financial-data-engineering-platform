# Phase 5 local Airflow orchestration

`financial_local` runs three tasks in order: `ingest_fixture` → `validate_fixture` → `dbt_build`. The first writes the Phase 4 synthetic RAW/OPS fixture to DuckDB. Validation checks committed batch count, unique batch IDs and configured entity coverage. dbt checks record counts, lineage and data quality before the runner publishes the analytics database.

Airflow uses manual triggering, no catchup, one active run, and one retry per task after 15 seconds. Each task has a three-minute execution limit. Upstream failure blocks downstream tasks. Each Airflow run has its own directory derived from the run ID. A filesystem lock serializes writes within a directory. Retries reuse the complete fixture, and dbt builds on a fresh copy. A failed build leaves any previously published analytics database intact.

## Run the local smoke test

With the Phase 4 Python environment, run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m orchestration.local smoke .local/phase5/smoke
.\.venv\Scripts\python.exe -m pytest --basetemp=.local/phase5-pytest
```

In a fresh virtual environment, install `requirements-dev.txt`, `requirements-dbt.txt`, and `requirements-dashboard.txt` together to exercise all locally runnable tests. After installation the host smoke and tests run offline.

The smoke command uses a local-only dbt target and disables telemetry. It keeps `fixture.duckdb` and `analytics.duckdb` under the supplied directory. To retry, use the same directory. To pick up fixture changes or recover from a corrupt fixture, use a new directory.

On a host with Docker Compose and Linux containers:

```powershell
docker compose build airflow-smoke
docker compose run --rm --no-deps airflow-smoke
```

The build pulls the versioned Airflow image and installs pinned top-level project dependencies in a separate task environment. After build, the one-shot Airflow run uses SQLite and `dag.test()`, with network isolation, no mounted host credentials, no published ports and no resident services. Task output goes to the console; the database files live in the disposable container. [Airflow DAG debugging documentation](https://airflow.apache.org/docs/apache-airflow/3.1.8/core-concepts/debug.html)

## Phase 7 hosted runtime check

The [manual GitHub Actions workflow](../.github/workflows/airflow-smoke.yml) runs the Compose commands above on an Ubuntu 24.04 standard runner with a 15-minute job timeout. The build needs registry and package index access. The runtime uses `network_mode: none`. The workflow passes no source or cloud secrets and requests read-only repository contents. GitHub offers standard runners free for public repositories. For an approved private run, confirm included minutes and billing before dispatch. [GitHub-hosted runner terms](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)

The smoke program discovers the DAG in an Airflow DAG bag and checks the three task dependencies and retry limits. A transient validation error must succeed on its second attempt and publish a fresh DuckDB database after all dbt tests pass. The program checks task order and queries for 21 committed batches, six FRED series and 12 selected SEC snapshots. A separate persistent validation failure must exhaust one retry, mark the transform upstream failed and leave the run without an analytics publication. CI logs contain the outcomes. This exercises the Airflow local test runtime. Scheduler and executor deployment remain outside the smoke scope.

The workflow has been prepared locally. Dispatch requires an approved remote with the workflow on its default branch, plus explicit authorization to run it. Record the run URL and results here after execution.

The concurrency group allows one smoke run at a time across refs. A new dispatch can replace an older pending run and leaves the active one running.

## Live DAG design

Keep the live DAG separate from `financial_local` and deploy it only after approval. The intended graph is **FRED ingestion and SEC ingestion → validate committed manifests → S3 transfer → Snowflake RAW load → Snowflake dbt build**. Start with manual runs and explicit selections, then enable a daily schedule after replay and failure checks. Keep catchup disabled. For manual backfills, validate an inclusive start and end, configured entities and a maximum window before doing work.

Use the existing `ingestion.pipeline.run_ingestion` callable behind the ingestion CLI. Persist the exact committed schema 2 manifest selections for the logical run, including the source, entity, run ID and stable batch identity. Before enabling ingestion retries, reconcile already-published entity batches to that selection across interrupted or partial runs. Serialize access to a shared archive and target. Pass only manifest identifiers between tasks and fail validation on missing or invalid requested batches.

Use `storage.transfer.prepare_batch` for local integrity validation and `S3Transfer.transfer` for immutable object and receipt publication. Use `SnowflakeLoader.load` for receipt verification and the transactional batch ledger. The current `transfer` and `load` CLI commands support explicit `--source`, `--entity`, `--run-id` and `--data-dir` selections. Retry transient transfer and load failures against the same manifests, bound timeouts, and block dbt until every selected load succeeds or reports an already committed batch. Record run, batch and task outcomes in Airflow and use the existing OPS ledger for committed load evidence. [Cloud loader contract](cloud-loader-contract.md)

## Checkpoint

- Implemented the fixture DAG, shared local task runner, isolated Compose smoke configuration and failure/retry regressions.
- The host smoke command against `.local/phase5/verification` and its same-directory retry each validated 21 committed batches. dbt reported `PASS=43 WARN=0 ERROR=0 SKIP=0` across 10 models, 2 seeds and 31 data tests.
- `python -m pytest --basetemp=.local/phase5-pytest` in the project environment reported 132 passed and one skipped. The skipped test imports Airflow to verify the DAG graph and retry configuration. The host also passed static DAG syntax and Compose YAML checks.
- A follow-up read-only query of the existing `.local/phase5/verification/analytics.duckdb` returned 21 committed batches, six distinct FRED series and 12 selected SEC snapshots.
- Airflow runtime verification is blocked on this Windows host. The environment checks and outstanding acceptance criteria are below. Live DAG wiring, daily scheduling, backfill controls and Snowflake/dbt parity remain pending. Cloud execution requires separate approval.

### Windows runtime check

| Check | Observed result |
| --- | --- |
| `Get-Command docker,docker-compose -ErrorAction SilentlyContinue` | Neither command resolved. |
| Docker Desktop and Compose file checks | Docker Desktop and its CLI were absent from the standard all-users and per-user install paths. No Compose plugin was found in the checked standard locations. No Docker engine pipe was visible. |
| `wsl.exe --status`, `wsl.exe --version`, `wsl.exe --list --verbose` | Each reported “The Windows Subsystem for Linux is not installed.” Exit codes were 50, 1 and 1, respectively. |

The Compose smoke did not execute, so there are no container logs. Airflow DAG discovery, task states, retry behavior, failure propagation and analytics publication from inside Airflow remain unverified. The earlier host tests cover the task runner and its DuckDB output.

The least disruptive next step is to use an existing machine with Docker Compose and a Linux container engine. On that machine, record `docker version` and `docker compose version`, then run the two Compose commands above and retain the build and run output. Confirm the discovered DAG ID, all three successful task states, the dbt totals and the published DuckDB contents before the disposable container exits. In a separate run, inject a task failure and check the single retry, downstream blocking and absence of a newly published analytics database. If verification must happen on this machine, enabling WSL 2 and installing Docker Desktop requires approval. [Microsoft WSL setup](https://learn.microsoft.com/en-us/windows/wsl/install) · [Docker Desktop Windows setup](https://docs.docker.com/desktop/setup/install/windows-install/)
