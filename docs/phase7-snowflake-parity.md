# Bounded Snowflake and DuckDB dbt comparison

**Status** · The local preflight passed against the preserved Phase 3B replay and a fresh DuckDB replay. Snowflake execution awaits separate approval. The one planned run uses the four original Phase 3B manifests with the default dbt cutoffs and the same project revision on both adapters. The loader for this test copies the validated local RAW and OPS input directly to a dedicated Snowflake database. AWS, FRED, and SEC access are outside this run.

## Local preflight

Use a read-only path to the existing published Phase 3B DuckDB replay and the original archive root, or use the fresh replay produced during Phase 7. The corresponding private Phase 3B plan identifies the archive path. Set the variables below to those paths. Run from the repository root with the project Python environment.

```powershell
python -m scripts.phase7_parity preflight "$replay" "$archive"
```

The command revalidates the four manifests, referenced raw and normalized files, batch IDs, receipt hashes, warehouse object IDs and raw body hashes. Expected warehouse input is four ledger rows, eight request occurrences, four unique raw objects, 91 changes, 136 SEC members and zero quarantines. Keep the archive and baseline read-only and use the same baseline file throughout the approved execution.

## Approval and cost

Refresh the current Snowflake account, AWS Ohio region, edition, eligible credit balance, Gen1 availability and credit rate with the account owner before seeking approval. The historical Ohio Enterprise basis is $3 per credit. One Gen1 X-Small cluster consumes one credit per hour, so 10 billable minutes model $0.50 of compute. Reserve $0.38 for cloud services and under $0.01 for transient storage, for about **$0.90 before tax or credits**. The working allowance is $5 at this rate. AWS cost is $0. Schedule one supervised 10-minute compute window, including any 60-second start minimums and idle tail, and stop after the first failure or at the end of the window. Require separate approval for another window or changed account terms. A one-credit warehouse monitor is a supplementary limit. Verify its availability and set it up before the run when supported. [Historical account basis](deployment-costs.md) · [Snowflake billing](https://docs.snowflake.com/en/user-guide/cost-understanding-compute) · [Warehouse settings](https://docs.snowflake.com/en/sql-reference/sql/create-warehouse)

## Approved execution

1. Stage the local Snowflake adapter environment and profile before the compute window. Install `requirements.txt` and `requirements-dbt-snowflake.txt` in a separate environment. Copy `dbt/profiles.example.yml` to `.local/phase7-parity/profiles.yml` and set `$parityDir = (Resolve-Path '.local/phase7-parity').Path` so dbt places its output under the intended directory. Set `FDEP_DBT_ACCOUNT`, `FDEP_DBT_USER`, and `FDEP_DBT_ROLE` for the approved browser-authenticated operator. Use `FDEP_DBT_DATABASE=FDEP_PARITY_DB`, `FDEP_DBT_WAREHOUSE=FDEP_PARITY_WH`, `FDEP_DBT_SCHEMA=FDEP_PARITY`, and `FDEP_DBT_QUERY_TAG=FDEP_PHASE7_PARITY`.
2. Confirm dedicated names are unused and create the two resources below under the authorized administrator role. Grant the scoped test role USAGE on the warehouse and database, USAGE on RAW and OPS, SELECT/INSERT on the six test input tables and UPDATE on RAW.SOURCE_OBJECT. Grant CREATE SCHEMA on this dedicated database so dbt can own its output schemas. Bootstrap the dedicated database using [RAW/OPS DDL](../warehouse/sql/001_raw.sql). Grant no privileges on existing warehouses or data to the test role.

```sql
CREATE TRANSIENT DATABASE FDEP_PARITY_DB DATA_RETENTION_TIME_IN_DAYS = 0;
CREATE WAREHOUSE FDEP_PARITY_WH
    WAREHOUSE_TYPE = 'STANDARD'
    WAREHOUSE_SIZE = 'XSMALL'
    GENERATION = '1'
    MIN_CLUSTER_COUNT = 1
    MAX_CLUSTER_COUNT = 1
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    ENABLE_QUERY_ACCELERATION = FALSE
    STATEMENT_TIMEOUT_IN_SECONDS = 120
    STATEMENT_QUEUED_TIMEOUT_IN_SECONDS = 30;
```

3. Run these commands in order. Check each exit code before continuing. Use the default cutoff variables on both engines. Record command output, build artifacts, query IDs, and resume and suspend times privately.

```powershell
python -m scripts.phase7_parity load "$replay" "$archive" --approved-cloud
python -m dbt.cli.main build --project-dir dbt --profiles-dir "$parityDir" --target snowflake --target-path "$parityDir/target" --log-path "$parityDir/logs"
python -m scripts.phase7_parity compare "$replay" "$archive" --approved-cloud
```

The load requires empty tables and copies the six relations in a single transaction, preserving the replay ledger timestamps for like-for-like comparison. Before committing it compares every RAW/OPS row, including raw bodies, with DuckDB. On error it rolls back. If a connection failure makes commit status unclear, inspect the six table counts and ledger from a fresh session before deciding whether to retry. A partial dbt build can leave views or seeds in this isolated database. Treat any build failure or parity mismatch as a failed test and capture evidence before teardown.

## Acceptance

The Snowflake build must pass 10 models, two seeds and 31 dbt data tests. The comparator requires exact column order and duplicates-sensitive equality of every row in the six input tables and all twelve dbt relations. It compares source value text and decimal values exactly, rejects floating-point projections and compares timestamps as instants. No value floors, relative tolerances or date truncation apply.

| Relation | Expected rows | Keys and selected data covered |
| --- | ---: | --- |
| Scope seeds | 6 series, 12 issuers | Series ID and cadence, ticker and zero-padded CIK |
| Committed batches and request lineage | 4 batches, 8 requests | Source/entity/sequence, batch ID, request index, manifest and object IDs, paths, hashes, observation and commit times |
| FRED staging and mart | 23 each | Batch, series, observation date, selected vintage, real-time dates, missing and quarantine flags, units and both lineage keys |
| SEC members, filings and facts | 136, 14, 122 | Batch, dataset and row ordinal, CIK, accession, form, filing/fact keys and source rows |
| Selected SEC snapshots | 1 | Issuer, selected batch sequence and ID, observation time and requested scope |
| SEC candidates and published facts | 25 each | CIK, taxonomy, tag, unit, period class and exact start/end, accession, filing date, amendment state, values and filing/fact provenance |

The bounded archive has zero quarantined records. Adversarial quarantine, amendment, ambiguity and cutoff cases remain covered by the local synthetic tests.

## Cleanup

Stop at the approved deadline, even after a failed or incomplete run. Cancel any still-running test queries using their query IDs, suspend `FDEP_PARITY_WH`, then drop the dedicated warehouse and transient database. Drop a test-role or monitor only if created for this run and included in the approval. Confirm `SHOW WAREHOUSES LIKE 'FDEP_PARITY_WH'` and `SHOW DATABASES LIKE 'FDEP_PARITY_DB'` return no matches and verify removal of any approved test grants, role or monitor. Reconcile posted warehouse, storage and cloud-services usage after the reporting lag. The historical replay database, production resources and original archive do not participate in teardown.
