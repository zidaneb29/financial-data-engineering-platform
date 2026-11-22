# Controlled AWS and Snowflake demonstration

The eight approved AWS resources are deployed in Ohio and the scoped transfer smoke tests passed. Use the existing `fdep-transfer` profile and dedicated bucket. See the [AWS smoke report](aws-deployment-smoke-report.md) and [Phase 3A assessment](phase3a-readiness.md). The Snowflake target is the existing AWS Ohio Enterprise trial. This runbook requires separate live authorization.

## Prepared scope and verified inputs

The source archive is .local/live-validation-66995445b3f349a2a380442d675db077/archive. Local revalidation checked all four v2 batches and retained the original file hashes. The new offline plan is .local/deployment-preparation-5c04b733af214d7585c2d6334551e9e6/plan.json. It contains exact command argument lists and expected per-batch counts.

Namespace fdep-demo yields 15 unique destination objects totaling 5,243,107 bytes when all four manifests and their ready receipts are transferred. Initial loading uses these two runs, one at a time.

| Stage | Source/run | Expected change rows | SEC snapshot members |
| --- | --- | --- | --- |
| First smoke test | DGS10 / 96d04564f8b74b6a81878d625fab00cf | 23 | 0 |
| Second smoke test | MSFT / 839006e36bb440afa08f3e450545d033 | 68 | 68 |
| Optional unchanged snapshot | DGS10 / 4d29fe84db5e40a08944fe95ab9b3fb3 | 0 | 0 |
| Optional unchanged snapshot | MSFT / 6f89fa0a43594598a5ec4a045ff89ca0 | 0 | 68 |

Replaying the same run ID must add no load rows or S3 uploads. Loading the optional snapshots adds distinct ledger/request memberships and the second SEC snapshot while preserving 91 cumulative change rows.

## Local tools and existing AWS deployment

Use the project virtual environment with Python 3.11.9 and the pinned cloud clients. Snowflake CLI and SnowSQL are optional. Check the reviewed AWS bucket, namespace and runtime identity locally, and refresh the short-lived source session if required. Before approved transfer, confirm `aws sts get-caller-identity --profile fdep-transfer` reports the expected `FdepTransferRuntime` assumed role. This demonstration reuses the deployed AWS infrastructure. AWS provisioning and infrastructure teardown require separate authorization.

## Snowflake resources, roles and authentication

The dedicated SQL artifacts are executed through an authorized administrator in an existing account. Stop if the fixed FDEP_DEMO names already belong to another use. Resource creation intentionally uses CREATE without replacement.

| Artifact | Execution and purpose |
| --- | --- |
| warehouse/sql/010_demo_resources.sql | SECURITYADMIN/USERADMIN/SYSADMIN create dedicated owner, loader and auditor roles, disabled service user, transient database and suspended warehouse |
| warehouse/sql/011_demo_budget.sql | ACCOUNTADMIN creates a one-credit monitor and attaches it to the dedicated warehouse |
| warehouse/sql/001_raw.sql | FDEP_DEMO_OWNER bootstraps RAW/OPS in FDEP_DEMO_DB using FDEP_DEMO_WH |
| warehouse/sql/020_demo_grants.sql | Owner grants data-loading privileges and read-only audit privileges |
| Locally generated bind-public-key.sql | SECURITYADMIN registers only the public key while the service user remains disabled |
| warehouse/sql/040_demo_reconcile.sql | Checks counts, raw hashes, duplicate event keys and commit records |
| warehouse/sql/050_demo_evidence.sql | Captures dedicated object settings and grants |
| warehouse/sql/090_demo_teardown.sql | Removes only the named dedicated demo resources after evidence capture |

The owner role inherits loader/auditor and is granted to SYSADMIN for administration. The disabled-at-creation SERVICE user gets the loader role as its primary role and starts with secondary roles disabled. Review effective PUBLIC grants before enabling it. The loader gets USAGE on the dedicated database, RAW/OPS and warehouse, SELECT/INSERT on current RAW tables and OPS.BATCH_LOAD, and SELECT/UPDATE on OPS.LOAD_MUTEX. It receives no account administration, schema creation, warehouse ownership or user-management rights. The auditor has SELECT plus required USAGE and is assigned to a human only if approved.

Phase 3B completed the live key-pair, S3 transfer, Snowflake load, replay, and synthetic rollback checks on November 21, 2026. All four batches reconciled to 91 change rows and 136 SEC snapshot memberships. The service user was disabled and the dedicated warehouse was suspended after the run. Sanitized execution and teardown evidence stays in `.local/phase3b-live/`. The earlier grant changes and accepted trial-specific exceptions are recorded in `.local/phase3b-preflight/public-revocation-execution.md`. Changes to account-wide grants require separate approval.

On the Enterprise account, the warehouse type is STANDARD. It is explicitly single-cluster, Generation 1, X-Small, initially suspended, with 60-second auto-suspend, auto-resume, disabled query acceleration and bounded statement/queue timeouts. Generation 1 is explicit because newer generations have different credit rates. If that generation is unavailable in the account, stop and reprice the supported configuration. The transient database uses zero-day retention to minimize retained demo storage. [Warehouse properties](https://docs.snowflake.com/en/sql-reference/sql/create-warehouse)

Before bootstrap, select the intended context explicitly.

~~~sql
USE ROLE FDEP_DEMO_OWNER;
USE DATABASE FDEP_DEMO_DB;
USE WAREHOUSE FDEP_DEMO_WH;
~~~

Execute 001_raw.sql outside a load transaction. DDL commits independently. Confirm exactly one OPS.LOAD_MUTEX row before permitting loads. Suspend the warehouse after bootstrap if configuration work will pause.

### Encrypted key preparation

Use a protected local credentials directory. For Windows, review its ACL and remove inherited access only with authorization, retaining the intended user's access. This changes directory permissions and was not performed during preparation. Store the private key under the ignored .local/credentials directory; retain it locally and restrict backups separately.

After the directory's permissions have been approved, generate into a fresh child directory.

~~~powershell
.\.venv\Scripts\python.exe -m scripts.generate_demo_key --directory .local/credentials/fdep-demo-key
~~~

The helper prompts twice, creates an encrypted PKCS#8 RSA-2048 private key, exports the public key and prints only the path and public fingerprint. It refuses to overwrite an existing directory. Compare its fingerprint with DESC USER after public-key registration. Confirm the effective grants and applicable policies before issuing the separate `ALTER USER FDEP_DEMO_INGEST SET DISABLED = FALSE` as SECURITYADMIN. [Snowflake key-pair authentication](https://docs.snowflake.com/en/user-guide/key-pair-auth)

Set the existing CLI variables in the operator's PowerShell session.

~~~powershell
$env:AWS_PROFILE = 'fdep-transfer'
$env:AWS_REGION = 'us-east-2'
$env:FIN_S3_BUCKET = 'approved-unique-bucket-name'
$env:FIN_ARCHIVE_NAMESPACE = 'fdep-demo'
$env:SNOWFLAKE_ACCOUNT = 'approved-account-identifier'
$env:SNOWFLAKE_USER = 'FDEP_DEMO_INGEST'
$env:SNOWFLAKE_DATABASE = 'FDEP_DEMO_DB'
$env:SNOWFLAKE_WAREHOUSE = 'FDEP_DEMO_WH'
$env:SNOWFLAKE_ROLE = 'FDEP_DEMO_LOADER'
$env:SNOWFLAKE_PRIVATE_KEY_FILE = (Resolve-Path '.local/credentials/fdep-demo-key/loader.p8').Path
$keySecret = Read-Host 'Key encryption passphrase' -AsSecureString
$env:SNOWFLAKE_PRIVATE_KEY_PASSPHRASE = [System.Net.NetworkCredential]::new('', $keySecret).Password
~~~

Replace account/profile/bucket placeholders locally. Keep passphrases out of transcripts, command arguments and committed files.

## Ordered dry-run and approved execution sequence

1. Recreate the local plan with python -m scripts.prepare_demo. Compare all source hashes to the reviewed plan. Run offline tests and resolve any changes.
2. Recheck AWS Ohio and the active Snowflake Ohio Enterprise trial, remaining balance, billing status, operator access, account authentication policies, PUBLIC grants, effective minimum retention, resource-name availability and budget. Use account metadata only for preflight.
3. After authorization, verify the existing AWS Ohio transfer identity and bucket and reuse the scoped profile. Review the separately approved Snowflake setup, smoke workload, and cleanup scope.
4. Prepare protected key files locally and start billing observation. In Snowflake execute 010, inspect generation, cluster counts and suspension settings, then attach the monitor with 011. If Gen1 is rejected or the reported settings differ, stop before warehouse use and reprice. Execute 001 in the owner/database/warehouse context, then 020. Register the public key and verify grants and the fingerprint before using the enabled service account.
5. Configure the operator session above. Verify the service-user Python login, expected role and JSON results. Transfer only the first FRED batch, then load it.
6. Run 040 and inspect one committed ledger row, 23 change rows, two raw request references, no SEC members and no quarantine. Re-execute the exact transfer/load commands and confirm no growth.
7. After the approved synthetic large-payload round trip succeeds, transfer/load the first SEC batch. Reconcile totals of two batches, four request references, four raw objects, 91 change rows and 68 SEC members. Replay the exact commands and verify unchanged totals.
8. If time and budget permit, transfer/load each second snapshot using run IDs from the plan. Expect four ledger entries, eight requests, 91 changes and 136 SEC members. Repeat selected operations to verify recovery/replay.
9. Capture evidence, suspend compute, execute approved Snowflake teardown and S3 object cleanup, then check later usage and billing updates.

The exact first FRED commands, from the repository root, are below. They are future execution steps requiring cloud approval.

~~~powershell
$demoArchive = '.local/live-validation-66995445b3f349a2a380442d675db077/archive'
.\.venv\Scripts\python.exe -m ingestion transfer --source fred --entity DGS10 --run-id 96d04564f8b74b6a81878d625fab00cf --data-dir $demoArchive
.\.venv\Scripts\python.exe -m ingestion load --source fred --entity DGS10 --run-id 96d04564f8b74b6a81878d625fab00cf --data-dir $demoArchive
.\.venv\Scripts\python.exe -m ingestion transfer --source sec --entity 0000789019 --run-id 839006e36bb440afa08f3e450545d033 --data-dir $demoArchive
.\.venv\Scripts\python.exe -m ingestion load --source sec --entity 0000789019 --run-id 839006e36bb440afa08f3e450545d033 --data-dir $demoArchive
~~~

The plan.json command lists cover all four runs. Save per-command JSON output under a fresh .local/demo-evidence directory, record exit codes, and stop after an unexpected failure to diagnose it before retrying.

## Reconciliation, failures and evidence

The S3 ready receipt is the transfer checkpoint. Local transfer journals pin expected hashes and record attempts. The warehouse ledger is the authoritative load checkpoint. A lost commit response is unknown until a fresh connection reconciles the same batch identity. Preserve local attempt journals and retry the exact same run rather than create a new ingestion identity.

S3 permission/credential failures require profile or policy correction. A checksum mismatch requires investigation of local/remote bytes. A blocked warehouse can require resource-monitor review or an administrator inspecting SHOW TRANSACTIONS/SHOW LOCKS for a detached session. Keep a failed warehouse suspended while investigating when possible. Never rerun setup SQL inside a load transaction.

Capture the reviewed plan and source hashes; Terraform validation/plan/state references; nonsecret account/role/region identifiers; bucket settings; Snowflake grant and warehouse-setting exports; public fingerprint; transfer receipts; CLI JSON reports; local transfer/load journals; reconciliation outputs before/after replay; and subsequent usage/billing results. Evidence and state stay under ignored local directories. Exclude private keys, passphrases, AWS tokens and debug HTTP headers.

The largest raw payload is 4,938,072 bytes. Before SEC, use the loader role in an explicit transaction and acquire the load mutex. Use the loader's insert-only MERGE and pyformat bind path with a dedicated synthetic object ID and valid synthetic JSON of comparable escaped and compressed sizes. Read back the text and verify its exact UTF-8 SHA-256, roll back, then use a fresh connection to check that the synthetic row is absent and the mutex version did not advance. Stop before SEC if this check fails or the transaction outcome remains unclear. Actual Snowflake binding, Unicode fidelity, JSON results, rollback and concurrent mutex behavior remain unverified. The first FRED load isolates basic compatibility before the larger SEC input. Amendment cases, other companies and other FRED frequencies remain outside this initial live scope.

## Teardown and completion evidence

Disable the service user, stop invocations, inspect active sessions and preserve receipts. Run 090_demo_teardown.sql as the indicated roles. Confirm whether the warehouse was already suspended before continuing past a redundant SUSPEND error. Dropping the dedicated transient database is intentionally destructive to demo cloud data; local source archives remain retained.

With the dedicated bucket and account verified, use the teardown administrator to list its objects and remove only this demo's contents. The prepared bucket is unversioned. If versioning or multipart transfer was enabled later, remove all versions/delete markers and incomplete multipart uploads explicitly. A separate policy allows deletion because the transfer role does not. Confirm an empty bucket. If separately authorized to remove the AWS infrastructure, review and execute the eight-resource Terraform destroy using the original state and approved variables. Terraform handles its managed policy attachment. force_destroy=false prevents implicit data removal by the template.

Verify that the dedicated Snowflake database, warehouse, user, roles and monitor are absent and that no project queries or sessions remain. If AWS infrastructure teardown was authorized, verify removal of all eight managed resources. Save SHOW results and console/CLI deletion evidence. Recheck account usage and billing after their reporting delays. Resource monitors, spending alerts and projected budgets are not guaranteed dollar caps.

## Approval boundary

Obtain separate approval for the named Snowflake resources, local encrypted key generation and public-key registration, bounded compatibility workload, staged financial-data transfer and load, verification and cleanup. The [cost estimate](deployment-costs.md) records the Ohio Enterprise basis. Consult the [Phase 3A report](phase3a-readiness.md) for outstanding checks.
