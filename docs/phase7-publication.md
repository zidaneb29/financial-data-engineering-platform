# Verification and publication checklist

The proposed destination is `zidaneb29/financial-data-engineering-platform` with public visibility. The candidate includes local ingestion, archived replay, DuckDB/dbt analytics, and a credential-free historical preview. The proposed MIT license covers project-authored code and documentation. The [preview data notices](../preview/NOTICE.md) cover the source data separately. The working repository has no commits or configured remote.

## Verification record

| Evidence | Observed outcome | Scope |
| --- | --- | --- |
| Fresh Windows environment, Python 3.11.9, installation from the documented requirements and `python -m pip check` | Installation succeeded and pip reported no broken requirements. | Public candidate copy with no private data |
| `python -m pytest --basetemp=.local/pytest` in the isolated checkout | 150 passed, one skipped because the Airflow SDK is absent. | Release candidate |
| `python -m orchestration.local smoke .local/fixture-verification` and a separate `dbt build --target local` against a copy of the private history | Each build passed all 43 nodes, including 31 data tests. | Synthetic fixture and isolated private history |
| `python -m pytest --basetemp=.local/phase7-acceptance` | 145 passed, one skipped because Airflow is absent on the host | Offline source parsing, paging, integrity, load replay and rollback, dbt selection, dashboard and orchestration |
| Existing local runner tests | Retried smoke runs reuse their fixture. An injected dbt failure preserves the previously published file. | Synthetic fixture |
| Fresh replay of the four private Phase 3B manifests, followed by `dbt build --target local` using the replay database | 43 nodes passed, including 31 tests. 91 change rows and 136 SEC snapshot memberships produced 23 DGS10 observations and 25 published Microsoft financial facts. All 18 input and output relations matched the earlier replay after excluding independently recorded commit timestamps. | Historical real source data, local warehouse replay |
| `python -m scripts.phase7_parity preflight` with the Phase 3B archive and DuckDB replay | Four manifests, four distinct RAW bodies and the associated receipt and object hashes validated. All twelve expected dbt relations were present. | Offline validation of real archived inputs |
| Streamlit API rendering with both local publications | All three tabs rendered. Subsequent browser verification covered the redesigned dashboard and the owner visually approved the private historical build. | Synthetic fixture and historical replay |
| Completed 2019–2025 capture | Verified 18 committed batches, including 3,934 FRED observation rows and 8,395 SEC snapshot members. The warehouse selected 3,682 company facts across twelve issuers. | [Private historical capture](dashboard-history.md#completed-20192025-capture) |
| Streamlit AppTest in an isolated copy | Rendered the three public preview tabs, 749 dated Treasury observations with gaps, and three Microsoft fiscal-year bars. The copy contained no private publication or archive and source credentials were cleared. | [Public historical preview](public-preview.md) |
| Phase 3B bounded AWS and Snowflake demonstration | Four committed batches, 91 changes, 136 SEC memberships, deterministic replay and rollback. Snowflake demonstration objects were removed and the eight AWS infrastructure resources were retained at the time of teardown. | Historical live RAW execution. Account records remain private. |
| Hosted Compose smoke | [GitHub Actions run 44985167711](https://github.com/zidaneb29/financial-data-engineering-platform/actions/runs/44985167711) passed DAG discovery, task dependency, retry recovery, downstream blocking, and DuckDB publication checks. | [Airflow runtime check](phase5-airflow.md#phase-7-hosted-runtime-check) |
| Snowflake dbt adapter build and comparison | Preflight and exact row comparator prepared. The Snowflake dbt build and exact cross-engine comparison were never executed. | [Parity runbook](phase7-snowflake-parity.md) |

The public quickstart opens the two reviewed extracts directly. The synthetic smoke build exercises the pipeline offline. Reproducing private historical counts requires the preserved source archive and manifests.

## Publication manifest

| Include | Files |
| --- | --- |
| Project entry and safe config | `README.md`, `LICENSE`, `AGENTS.md`, `pyproject.toml`, `requirements*.txt`, `.env.example`, `.gitignore`, `.gitattributes`, `.dockerignore`, `compose.yaml`, `config/` |
| Source and database contracts | `ingestion/`, `storage/`, `warehouse/`, `dbt/`, `infrastructure/` |
| Presentation, orchestration and reproduction tools | `dashboard/`, `orchestration/`, `.github/workflows/airflow-smoke.yml`, `scripts/`, `tests/` |
| Reviewed public data | `preview/treasury-10y.csv`, `preview/microsoft-revenue.csv`, `preview/NOTICE.md` |
| Methodology, limits and historical evidence summaries | `docs/` |

Keep source downloads, local archives and manifests, object exports, private contact details, credential profiles and keys, cloud account IDs and deployment output outside the public file set. Keep Terraform state and plans, virtual environments, DuckDB files, dbt output and profiles, Airflow metadata, test scratch directories and logs ignored. `.env.example` is the public environment template. The versioned Terraform provider lock is a reproducibility input. Pinning covers direct Python dependencies and the Airflow image tag. Transitive dependency and container rebuilds can vary.

The unstaged inventory has 134 files. It contains 15 root files, 27 documentation files, 21 dbt files, 18 tests, 12 warehouse files, eight scripts, seven ingestion files, six dashboard files, five each for infrastructure, orchestration and storage, three preview files, one config file and one workflow. The two preview CSVs total 18,741 bytes. The exact local inventory is saved under ignored release evidence.

## Final review

- [x] Review candidate paths for key material, token patterns, credential assignments, account identifiers, and machine-specific paths. Replace user profile paths and live bucket names with portable instructions or placeholders. Test sentinel values remain in offline fixtures.
- [x] Keep generated evidence under ignored paths and publish prose and reproducible commands. Exclude nested dbt output and verify that the file list contains source, configuration and documentation.
- [x] Describe the synthetic, historical local, and historical live outcomes explicitly. Record the successful hosted Airflow run and identify Snowflake/dbt parity as unexecuted.
- [x] Confirm the proposed preview contents against their primary sources, regenerate the extracts byte for byte, and verify the preview in an isolated copy.
- [x] Verify the Airflow workflow's manual trigger, read-only checkout, 15-minute limit and serial dispatch group. The Compose smoke container runs with networking disabled and receives no cloud credentials.
- [ ] Confirm ownership and the MIT copyright notice. Authorize the initial commit separately from creating and pushing to the proposed public repository.
- [ ] Review the exact staged tree against this manifest, rerun the candidate secret/path scan against that tree and check that the intended visibility is set before publication.
- [x] Verify the single manual hosted Airflow dispatch.
The optional Snowflake/dbt parity run is outside project closeout.

## Phase 7 change inventory

| Area | Added or updated |
| --- | --- |
| Dashboard | `dashboard/app.py`, `dashboard/plots.py`, `tests/test_dashboard.py`, `docs/phase6-dashboard.md` |
| Airflow verification | `.github/workflows/airflow-smoke.yml`, `.dockerignore`, `compose.yaml`, `orchestration/airflow_smoke.py`, `docs/phase5-airflow.md` |
| Snowflake adapter comparison | `scripts/phase7_parity.py`, `dbt/profiles.example.yml`, `docs/phase4-dbt.md`, `docs/phase7-snowflake-parity.md` |
| Publication and redaction | `README.md`, `.gitignore`, `docs/architecture.md`, `docs/account-preparation.md`, `docs/aws-account-plan-review.md`, `docs/aws-deployment-smoke-report.md`, `docs/phase2c-validation.md`, `docs/runtime-identity-plan.md`, `docs/phase7-publication.md` |
