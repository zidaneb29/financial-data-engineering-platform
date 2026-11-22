# Phase 3A Snowflake deployment readiness

Assessment date November 21, 2026 (America/New_York). The user accepted the existing Enterprise trial. The [controlled deployment runbook](controlled-deployment.md) is the execution plan and the [cost estimate](deployment-costs.md) supersedes the earlier Standard estimate.

## Verified account and billing

| Check | Evidence |
| --- | --- |
| Cloud and region | Snowsight account selector showed AWS and `us-east-2.aws` (Ohio). |
| Edition | Snowsight Account Details showed Enterprise. |
| Trial and balance | The ACCOUNTADMIN trial tile showed $400 of $400 and “Trial ends in 30 days.” User confirmed the November 21 start. Approximate calendar expiry is December 21, 2026. Exact timestamp is unverified and earlier balance depletion is possible. |
| Payment and conversion | Admin → Billing → Snowflake billing → Payment Method showed an add-card control and stated that charging starts only after upgrading. No saved method was displayed. The trial tile separately offered Upgrade. |
| Browser access | The existing authenticated Snowsight session was accessible. No credentials were captured and no SQL was issued. |

For Snowflake’s direct self-service trial, a payment method is optional while on trial. At expiry or depletion Snowflake suspends the account unless the user explicitly upgrades. Adding a card alone does not convert it. On-demand billing and automatic threshold payments can follow an explicit upgrade. No account change was made. [Snowflake trial terms](https://docs.snowflake.com/en/user-guide/admin-trial-account)

## Local connector and authentication

- Python 3.11.9 and connector 4.8.1 imported from the existing virtual environment. `python -m pip check` in that environment found no broken requirements.
- The 4.8.1 cursor reported `CAN_USE_ARROW_RESULT_FORMAT=True` on this run, superseding the earlier failed import observation for this probe. No Arrow fetch was exercised. The loader requests JSON and uses ordinary cursors for counts, digests and text. Exact numeric values are converted with Decimal for insertion into NUMBER(38,12); reconciliation can select numeric values as text for exact comparison. No dependency or Windows policy change was needed.
- The connection factory takes a local encrypted PKCS#8 key path and the 4.8.1 passphrase parameter `private_key_file_pwd`. The installed connector selects key-pair authentication when a private key file is supplied. After approval, protect the key directory using Windows ACLs, prompt locally for the passphrase, register only the public key, compare its fingerprint, then enable the service user. Check account network and authentication policies before enabling. Keep admin browser access and the service identity separate. No key was generated for the account, and live Python login and JSON fetch remain pending. [Connector authentication](https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-connect) · [Key-pair setup](https://docs.snowflake.com/en/user-guide/key-pair-auth)

## SQL and permissions assessment

The documented commands support the proposed Enterprise deployment. The SQL provisions a transient database with zero-day configured retention, RAW and OPS tables, dedicated owner/loader/auditor roles, and a disabled SERVICE user with the loader primary role and no secondary roles active by default. Verify effective retention, PUBLIC grants, name collisions and account policy during preflight. Role ownership and inheritance are consistent with the built-in role hierarchy. Grant the runtime role warehouse, database and schema USAGE; SELECT/INSERT on the reviewed load tables; and SELECT/UPDATE on the mutex. The auditor uses read-only table privileges with required USAGE. Privileged setup, monitoring and teardown use the operator’s administrative roles. Verify these grants and validate allowed/denied operations during the approved run. [Access control](https://docs.snowflake.com/en/user-guide/security-access-control-overview) · [Privileges](https://docs.snowflake.com/en/user-guide/security-access-control-privileges) · [Trial feature limits](https://docs.snowflake.com/en/user-guide/admin-trial-account#current-limitations-for-trial-accounts)

Enterprise is the account edition. The warehouse type is STANDARD, Generation 1, X-Small and explicitly single-cluster. It starts suspended with 60-second auto-suspend, demand-driven auto-resume, disabled query acceleration and bounded query/queue timeouts. Documentation supports the explicit Gen1 SQL syntax. Account-specific acceptance remains unverified. Capture SHOW WAREHOUSES after approved creation and stop before running work if the settings differ. Attach the one-credit monitor before bootstrap. [CREATE WAREHOUSE](https://docs.snowflake.com/en/sql-reference/sql/create-warehouse) · [Warehouse generation](https://docs.snowflake.com/en/user-guide/warehouses-gen2)

## Integration and verification gates

The existing client validates the v2 archive, checks the S3 ready receipt and referenced hashes using the scoped AWS runtime identity, and sends records to Snowflake through the local Python client. It preserves source payloads and provenance and commits records and the load ledger together. This flow requires no external stage, storage integration, extra service or always-running compute.

| Checkpoint | Expected evidence |
| --- | --- |
| First DGS10 batch | One ledger row, two requests, two unique raw objects, 23 changes, zero SEC members and zero quarantine rows. |
| First Microsoft batch | Cumulative two ledger rows, four requests, four unique raw objects, 91 changes and 68 SEC members, with zero quarantine. |
| Optional two unchanged snapshots | Cumulative four ledger rows, eight requests, four unique raw objects, 91 changes and 136 SEC members. The second SEC snapshot adds 68 members and zero changes. |
| Precision and source provenance | Compare each bounded dataset to its manifest-linked rows by dataset and ordinal, checking original numeric text and exact stored decimal including nulls. Export VALUE_NUMBER as VARCHAR and compare with Decimal. Check request endpoint, redacted parameters, timestamp, object key and SHA-256 against the reviewed manifests and receipt. Compare the full SEC candidate membership including accession, source row, dates, tag and unit. Duplicate, orphan, quarantine and raw-hash diagnostics must be empty. |
| Replay and interruption | Reuse each exact run ID. Expect zero additional S3 uploads and no changes to committed database rows or memberships. On timeout or lost commit response, stop and reconcile through a fresh connection using the same receipt/manifest hashes and authoritative ledger. A matching committed ledger and verified counts means replay. An absent ledger after rollback permits retry. A mismatch or unresolved transaction requires investigation before retry. |

Before the real SEC batch, run an approved synthetic probe using a similarly sized and compressible payload with the same connector and bind path, then verify hash fidelity and rollback. The largest Company Facts object is 4,938,072 bytes. An offline probe using `SnowflakeConverter.escape`, `quote` and `gzip.compress` produced a 4,938,168-byte literal and 318,096 compressed bytes. This measures a local literal and does not establish the complete wire request or Snowflake behavior. Snowflake applies its 1 MB query-text guidance after compression, including binds, and larger statements risk truncated retry metadata. A failed synthetic probe blocks the SEC load pending a revised transport plan. [Query text size guidance](https://docs.snowflake.com/en/user-guide/query-size-limits)

## Verification and approval

From the repository root:

- `./.venv/Scripts/python.exe -m pytest --basetemp <fresh ignored .local path> --tb=short` passed all 128 tests. Cloud SDK stubs and transaction doubles verified simulated behavior. The bare `python` command resolved to the inaccessible Windows Store alias; the existing virtual environment supplied Python 3.11.9.
- `./.venv/Scripts/python.exe -m pip check` reported no broken requirements. A separate local connector import printed `4.8.1 True` for version and Arrow availability.
- `./.venv/Scripts/python.exe -m scripts.prepare_demo` revalidated the existing four v2 manifests and archived input hashes. The ignored plan reported 15 S3 objects totaling 5,243,107 bytes, 91 changes, 136 snapshot members and zero quarantined rows. The original archive was unchanged.
- Prior live AWS smoke evidence establishes upload, exact readback, replay and scoped denials. This phase made no AWS calls. Snowflake SQL acceptance, live grants, live Python connectivity, warehouse metering, precision and transaction semantics remain deployment checks.

The modeled total is **$1.93 before credits and tax**, with expected cash cost near $0 subject to eligible credits. Confirm balances and account policy before running work.

Separate live authorization must cover creation of the dedicated database/schemas/tables, roles, warehouse, monitor and service user; local key preparation and public-key registration; bounded Python authentication/JSON and synthetic payload checks; the staged S3 transfers and Snowflake loads with verification/replay; and prompt suspension, dedicated Snowflake teardown and demo-object cleanup. Any AWS infrastructure change or destruction, Snowflake upgrade, or proposed spend beyond the agreed scope requires separate approval. This assessment created no cloud resources and executed no financial load.
