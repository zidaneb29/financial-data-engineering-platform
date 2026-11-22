# S3 transfer and Snowflake RAW loading

The scoped AWS Ohio S3 transfer path passed [live smoke tests](aws-deployment-smoke-report.md). The Snowflake Ohio Enterprise trial was verified in Snowsight. Live Snowflake service login, SQL execution and load remain pending separate approval. See the [Phase 3A report](phase3a-readiness.md).

## Execution model

The CLI retains local ingestion commands and adds transfer and load. The uploader accepts validated v2 batches, pins their identities and hashes locally, verifies destination bytes, and publishes a remote ready receipt last. The warehouse loader requires the local archive and matching verified S3 receipt. It verifies every transferred object and submits parameterized records through a dedicated Snowflake connection.

This initial loader uses client-mediated DML for the small demonstration universe. It preserves raw JSON as text and uses explicit transaction control. External stages, COPY loading, and a Snowflake S3 storage integration remain a later optimization when volume justifies them. DDL belongs to separate schema setup because it implicitly commits an active transaction. [Snowflake transactions](https://docs.snowflake.com/en/sql-reference/transactions)

## Configuration and CLI

Use requirements.txt for ingestion only, requirements-cloud.txt for cloud clients, or requirements-dev.txt for the full offline test environment. SDK imports occur only in cloud commands and SDK-specific tests.

| Variable | Required purpose |
| --- | --- |
| AWS_PROFILE | Approved local AWS profile, including refreshed SSO credentials where applicable. Standard AWS credential environment variables are also supported. |
| AWS_REGION | Region of the existing S3 bucket |
| FIN_S3_BUCKET | Existing dedicated private archive bucket |
| FIN_ARCHIVE_NAMESPACE | Stable single-component namespace using letters, digits, underscore or hyphen |
| SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER | Existing account identifier and service user |
| SNOWFLAKE_DATABASE, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_ROLE | Existing dedicated database, small auto-suspending warehouse and least-privilege loader role |
| SNOWFLAKE_PRIVATE_KEY_FILE | Local key-pair authentication file matching the user's configured public key |
| SNOWFLAKE_PRIVATE_KEY_PASSPHRASE | Local passphrase when the key is encrypted |
| FIN_DATA_DIR | Local archive root, defaulting to .local/data |

The CLI fails configuration checks with guidance and suppresses cloud exception details that could expose credentials. It requires a configured profile or explicit AWS environment credentials before invoking boto3 credential resolution. Runtime configuration must be set in the shell or supplied by a local environment runner. Preserve private key files and local environment files outside source control.

The following commands are for a future authorized cloud run after setup and cost approval.

~~~powershell
.\.venv\Scripts\python.exe -m ingestion transfer --source fred --entity FEDFUNDS --run-id <committed-run-id>
.\.venv\Scripts\python.exe -m ingestion load --source fred --entity FEDFUNDS --run-id <committed-run-id>
.\.venv\Scripts\python.exe -m ingestion transfer --source sec --entity 0000789019
.\.venv\Scripts\python.exe -m ingestion load --source sec --entity 0000789019
~~~

Omitting run-id selects all committed batches for the source entity, in sequence order. Already transferred batches are verified and reused. Already loaded batches reconcile through the warehouse ledger. A failed entity batch produces a failure report and a nonzero command exit while independently valid selected batches can still progress. Loader recovery uses a fresh connection on the next invocation.

The pinned Snowflake connector is 4.8.1. Connector 5.2.0 could not import under this host's Windows application-control policy. An earlier check reported the optional Arrow extension blocked. The Phase 3A import probe succeeded and reported Arrow availability in the connector, without exercising Arrow fetches. The loader continues to request JSON for ordinary cursors. Actual key-pair authentication and JSON result retrieval remain live checks.

## Transfer identity and S3 layout

The batch ID hashes namespace, source, entity and run_id through the canonical serializer. The receipt pins the exact manifest-file hash, its internal checksum, and each dependency's path, hash and size. The receipt is deterministic and has no changing transfer timestamp.

~~~text
<namespace>/raw/<source>/<entity>/<endpoint>/<sha256>.json
<namespace>/processed/<source>/<entity>/<run-id>/<dataset>.jsonl
<namespace>/metadata/batches/<source>/<entity>/<sequence>.json
<namespace>/ready/<batch-id>.json
~~~

Local transfer state lives at metadata/transfers/destination-hash/batch-id.json. The destination hash includes bucket and namespace. A state file pins the receipt before any write and records attempts. Rewriting a locally valid manifest under an already pinned identity is rejected. Source files are retained.

For each object, the uploader first checks for existing bytes. New objects use a conditional If-None-Match write, an explicit SHA-256 request checksum and AES256 server-side encryption. Readback computes SHA-256 independently over the returned body. A conditional conflict after a lost response is resolved through readback. The manifest is uploaded after raw and normalized dependencies. The ready receipt is published only after verification. ETags have no role in the integrity decision. [boto3 put_object](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html)

Transient SDK connection failures and selected service errors have up to four attempts with bounded exponential backoff. Permanent errors and content conflicts fail the batch. Successful state is written only after ready verification. A crash after ready publication can be reconciled without duplicate uploads. Remote objects are reverified even when a local checkpoint says success, so later corruption cannot be hidden by the checkpoint.

Objects and batches are buffered in memory. This implementation uses single-object PUT operations and targets modest local batches. Multipart transfer, remote-only reconstruction and streaming large objects are deferred. Readback verification adds GET requests and potentially outbound-transfer cost.

## RAW schema

warehouse/sql/001_raw.sql defines tables in an existing dedicated database. It is an administrator setup artifact and the loader never runs it. Bootstrap the mutex once from a single setup session.

| Table | Grain and retained data |
| --- | --- |
| RAW.SOURCE_OBJECT | One namespace/object-key identity, retaining SHA-256 and raw JSON text. Shared raw objects are reused across batches. |
| RAW.BATCH_OBJECT | One request reference per batch and request index, with object identity, endpoint, safe parameters and retrieval timestamp |
| RAW.INGESTION_RECORD | One normalized change per batch, dataset and dataset-local row ordinal, including full row text and checked numeric projection |
| RAW.SEC_SNAPSHOT_MEMBER | One distinct replayed SEC filing/fact member per batch, dataset and dataset-local ordinal, including unchanged candidates |
| RAW.NUMERIC_QUARANTINE | One unsupported numeric projection per batch, record kind and ordinal, retaining value text and row provenance |
| OPS.BATCH_LOAD | One committed batch ID, pinned manifest/receipt hashes and text, expected counts and completion time |
| OPS.LOAD_MUTEX | One initialized control row that cooperating loader transactions update before accessing the commit ledger |

FRED observations and SEC filings/facts retain their complete normalized fields in PAYLOAD_TEXT, including accession, dates, amendments, source units and raw-object references. This is a RAW landing design. Relational staging and analytical dimensions remain later transformations.

## Transaction and recovery

The loader opens a dedicated session, begins a transaction, updates the existing mutex row, and reads the ledger. Cooperating sessions serialize through that update. The loader rejects an absent or duplicated mutex row. This is necessary because ordinary table key declarations do not provide enforced batch uniqueness. Live contention behavior remains unverified.

For a new batch, it merges raw objects, checks their stored hashes and text, inserts request memberships, normalized changes, SEC snapshot memberships and quarantine records, then inserts the commit-ledger entry. It reconciles counts before commit. All loading statements are DML or SELECT. Client-side pyformat bindings and bounded INSERT groups avoid connector executemany paths that can create a temporary stage.

A pre-commit exception triggers rollback. A lost commit response records unknown status. Retrying on a new connection checks the ledger before inserting anything. A local checkpoint failure after a successful commit is resolved the same way. A matching ledger entry must have the expected manifest hash, receipt hash and record counts. A mismatched entry or incomplete batch is rejected.

Load attempt journals live at metadata/loads/target-hash/batch-id.json. The target hash includes account/database configuration context. They are local operational evidence. The committed warehouse ledger is authoritative. Source sequence is retained in the manifest and is independent of warehouse arrival order.

Statement and lock timeouts bound normal waiting. If a lost session leaves a detached transaction blocking future work, an administrator must inspect SHOW TRANSACTIONS and SHOW LOCKS and resolve the identified transaction before retrying. This requires account-specific investigation during the demonstration.

## Numeric preservation

Raw JSON is stored as VARCHAR text to retain values that could exceed warehouse numeric or VARIANT parsing limits. Original bytes remain in the local/S3 archive. Normalized decimals remain exact VALUE_TEXT strings. The optional VALUE_NUMBER landing projection is NUMBER(38,12), allowing 26 integer digits and 12 fractional digits.

checked_decimal inspects exact Decimal digits and exponent without quantizing or passing through float. Unsupported magnitude, fractional scale or non-finite values are rejected by conversion. The loader retains the source text, writes a null numeric projection and records the failed projection in NUMERIC_QUARANTINE. The RAW batch can commit with numeric_status=quarantined because source fidelity was preserved. Analytical publication must resolve these records before claiming complete numeric coverage. Source-missing FRED values remain distinct from quarantined projections.

This landing projection is provisional and does not finalize business metric types. Actual FRED/SEC profiling remains necessary before later schema decisions. An object or record exceeding the configured 16 MiB warehouse text bound fails the load. [Snowflake numeric types](https://docs.snowflake.com/en/sql-reference/data-types-numeric)

## Setup, cost and teardown

The [controlled deployment runbook](controlled-deployment.md), [itemized estimate](deployment-costs.md) and [Phase 2D preparation report](phase2d-report.md) now specify the proposed demonstration resources and approval boundary.

The Terraform template prepares one private S3 bucket, default SSE-S3 encryption, public-access blocking, enforced ownership, TLS-only access and a scoped transfer policy. It creates no compute. An administrator must attach the policy to an approved existing role. Object access is restricted to the namespace. ListBucket on the dedicated bucket lets missing-object reads return usable absence responses. Deletion remains an administrator task. Terraform is unavailable on this host, so formatting and provider validation were not run.

For Snowflake, use an existing or explicitly approved account and dedicated database. Set an X-Small warehouse to auto-suspend and configure budget controls before running setup SQL. The runtime role needs database/schema and warehouse USAGE, table SELECT and INSERT, and UPDATE on OPS.LOAD_MUTEX. Schema creation and role administration belong to setup privileges.

Before any paid execution, calculate region- and account-specific S3 storage, PUT/GET and returned-byte transfer charges plus Snowflake compute and retained storage. Warehouse starts have a one-minute minimum. Include readback and replay verification in the request estimate. Check actual trial/credit eligibility in the accounts and request approval against the $0–$10 target and $15 planned ceiling. This phase made zero cloud service calls. [S3 pricing](https://aws.amazon.com/s3/pricing/) · [Snowflake warehouse considerations](https://docs.snowflake.com/en/user-guide/warehouses-considerations)

For teardown after the approved demonstration, stop pipeline invocations, capture sanitized receipts and load results, and suspend the warehouse. Remove the dedicated Snowflake database and warehouse and revoke project-specific grants or users as appropriate. Check retention-related storage and billing after removal. Empty only the dedicated S3 bucket, including versions/delete markers or multipart leftovers if those features were later enabled. Terraform force_destroy is false, so emptying requires deliberate operator action. Detach the transfer policy, then review and execute Terraform destroy for the matching project state. Verify bucket absence, policy removal, Snowflake resource removal, stopped sessions and later billing updates.

## First controlled demonstration

Use the [Phase 2C local validation command](phase2c-validation.md#secure-windows-configuration-and-execution) to collect source evidence before the cloud steps below.

1. Configure source credentials locally, ingest one real FRED series and one SEC issuer, repeat ingestion, and inspect units, dates, mappings, amendments, precision and v2 manifests.
2. Validate Terraform with an installed CLI and review the plan. Prepare actual AWS/Snowflake account configuration, region choices and cost estimate, then obtain deployment approval.
3. Establish the dedicated resources and least-privilege identities. Run schema SQL outside loading transactions and verify the single mutex row.
4. Transfer one selected real v2 batch, verify its receipt, and run one RAW load. Repeat both operations and reconcile counts and hashes.
5. Validate actual Snowflake parameter binding, transactional rollback, lost-response recovery, locking, Unicode/decimal fidelity and JSON result retrieval. Capture genuine evidence.
6. Expand to the second source only after resolving observed issues, then perform and verify teardown.
