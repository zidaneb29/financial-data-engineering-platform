# Development roadmap

| Phase | Deliverable | Exit check |
| --- | --- | --- |
| 0. Foundation | Source scope, contracts, architecture, repository rules and test setup | Run credential-free configuration checks |
| 1. Local ingestion | Python CLI, FRED and SEC clients, local raw archive and complete batch manifests | 38 offline tests passed. Live API payload checks await local configuration. See [Phase 1 verification](local-ingestion.md#verification). |
| 1.5. Readiness audit | Local source validation and warehouse interface review | 38 offline tests passed again on November 19. Live configuration is absent. See [audit findings and transfer requirements](phase15-audit.md). |
| 2A. Local hardening | Schema 2 manifests, strict batch validation, durable sequences and SEC snapshot selection | 80 offline tests passed on Python 3.11.9. See [hardening verification](phase2a-report.md) and the [loader contract](cloud-loader-contract.md). |
| 2B. Cloud integration implementation | S3 transfer, Snowflake RAW loader, numeric quarantine, CLI and deployment templates | 122 offline tests passed on Python 3.11.9. See [integration guide](cloud-integration.md) and [Phase 2B report](phase2b-report.md). |
| 2C. Live source validation | Source configuration, host transport, local evidence collection and financial correctness review | Live DGS10/MSFT ingestion and replay verified. Real-data fixtures passed simulated transfer/load reconciliation. See [verified results and remaining checks](phase2c-validation.md). |
| 2D. Controlled deployment preparation | Tool inspection, dedicated Snowflake setup, key preparation, dry-run plan, pricing and teardown | 128 offline tests passed. Terraform validation, target account confirmation and deployment authorization remain pending. See [preparation report](phase2d-report.md). |
| 3B. S3 to Snowflake demonstration | Four committed batches, deterministic replay, reconciliation and rollback | Verified Snowflake teardown and S3 object cleanup. Private evidence is in .local/phase3b-live. |
| 4. Transformation | dbt staging, marts, lineage and data tests | DuckDB passed 31 data tests on synthetic fixtures and a replay of the four Phase 3B batches. Snowflake execution requires separate approval. See [Phase 4 verification](phase4-dbt.md#observed-verification). |
| 5. Orchestration | Manual fixture DAG and single-container smoke run first, daily scheduling after local verification | Host task workflow verified. Container execution, Airflow task states and live DAG wiring remain pending. See [Phase 5 checkpoint](phase5-airflow.md#checkpoint). |
| 6. Analytics | Financial SQL, Power BI Desktop report and health page | Verify filters, periods, units and reported metrics against exported data. Evaluate optional market data. |
| 7. Cloud demonstration | Terraform validation, approved S3 and Snowflake run, execution evidence and teardown | Verify loads, dbt output, dashboard export, resource removal, and billing follow-up. |
| 8. Publication | Public README, screenshots, license decision and repository audit | Reproduce setup, review secrets and data rights, and prepare GitHub publication. |

## Repository layout

The repository contains config/, ingestion/, storage/, warehouse/, dbt/, orchestration/, tests/, docs/ and infrastructure/terraform/. Dashboard work follows orchestration.

## Phase 0 environment

| Tool | Observed on the development host | Needed for |
| --- | --- | --- |
| Git | 2.55.0.windows.5; existing empty repository with no remote | All phases |
| Python | 3.11.9 at `%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe`; the Windows Store alias fails and `py` lists no registered interpreter. Codex also has a bundled Python 3.12.14. | Phase 0 and Phase 1 |
| Docker and Compose | Docker absent from PATH and the default Docker Desktop install path. The WSL launcher reports WSL is uninstalled. | Phase 5 |
| Terraform, AWS and Snowflake CLIs | Absent from PATH | Later cloud work. Use SDKs or SQL where practical and install CLIs only if needed. |
| dbt and Airflow | Absent from PATH | Phases 4 and 5. Install in the project's chosen isolated environments. |
| Power BI Desktop | Planned. Availability and licensing to be verified in Phase 6. | Phase 6 |

Phase 1 needs a working Python environment and the dev requirements. Live FRED calls need a user's own application key. Live SEC calls need an identifying User-Agent. Neither variable was configured during the Phase 0 check. Official documentation was reviewed, but authenticated FRED access and SEC API payload handling remain unverified. The browser-based SEC endpoint check did not return a payload.

### Verification on November 17, 2026

- `.\.venv\Scripts\python.exe -m pytest` passed both configuration checks with Python 3.11.9 and pytest 8.4.2.
- `.\.venv\Scripts\python.exe -m pip check` found no broken requirements.
- `git check-ignore` confirmed that the virtual environment, local data, environment file, private keys, and Terraform state are ignored. The example environment file is available for version control.
- Git was already initialized. No commits, remote changes, publications, or cloud deployments were made.

## Phase 2 handoff

Use local configuration to verify one FRED series and one SEC issuer before expanding to the full universe. Profile real filing periods, allowed units, precision, and unmatched accessions before finalizing physical Snowflake types. Use successful entity manifests as the transfer and replay boundary. Validate object checksums, carry forward accession and retrieval timestamps, and test idempotent load behavior offline before an approved cloud demonstration.


