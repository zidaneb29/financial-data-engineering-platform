# Phase 2B implementation and offline verification

Phase 2B implements validated S3 transfer, Snowflake RAW loading and cloud command wiring. Existing ingestion interfaces and source artifacts are preserved. Cloud execution remains unverified.

## Verification

The final offline suite passed with **122 passed, 0 failed** on Python 3.11.9 and pytest 8.4.2 in **25.48 seconds**. This includes the existing 80 tests and 42 cloud integration cases.

~~~powershell
$testRoot = '.local/phase2b-tests-' + [guid]::NewGuid().ToString('N')
.\.venv\Scripts\python.exe -m pytest --basetemp $testRoot --tb=short
~~~

The new cases cover cloud CLI configuration, boto3 conditional-write request shapes, deterministic transfers, corruption, retries and lost responses, transfer checkpoint recovery, transactional rollback, unknown commits, post-commit journal failure, ledger reconciliation, exact numeric boundaries, quarantine, raw provenance and unchanged/withdrawn SEC membership.

SDK request validation used boto3 1.44.6 and botocore Stubber. Snowflake connector 4.8.1 imported without connecting. The transaction double exercises the Python protocol and failure handling but does not execute SQL against Snowflake. Ordinary tests block socket connections and requests HTTP sends. No live source or cloud service verification is claimed.

pip check found no broken requirements, Python compilation succeeded, CLI help rendered, and ignore checks confirmed exclusions for local artifacts, private keys, Terraform variables and state. Terraform itself was unavailable, so its CLI validation remains open.

## Components and changes

| Files | Implemented behavior |
| --- | --- |
| storage/transfer.py | Validated v2 preparation, deterministic object keys, pinned receipts, retries, conditional writes, independent readback, ready-last publication and durable transfer attempts |
| storage/cloud_cli.py, ingestion/__main__.py | Separate transfer/load commands, configuration guidance, lazy SDK loading and safe failure reports |
| warehouse/loader.py | Verified transferred inputs, transactional DML, raw-object reuse, normalized changes, SEC snapshot membership, numeric quarantine, reconciliation and recovery journals |
| warehouse/numeric.py | Exact checked fixed-precision conversion without float or rounding |
| warehouse/sql/001_raw.sql | Separate RAW/OPS schema initialization and single-row mutex bootstrap |
| infrastructure/terraform/ | Private encrypted S3 bucket, scoped transfer policy and example variables. Definitions were prepared but not applied. |
| requirements-cloud.txt, requirements-dev.txt, .env.example | Pinned cloud SDKs, full offline test dependencies and local cloud configuration fields |
| tests/cloud_doubles.py, tests/test_cloud_*.py, tests/test_warehouse_loader.py, tests/conftest.py | Service/transaction doubles, SDK Stubber checks, failure and precision regressions, CLI coverage and socket-level offline guard |
| README.md and docs/ | Concise public status, implemented contracts, RAW design, costs, setup and teardown guidance |

## Decisions and limits

The initial warehouse loader uses parameterized DML through the client after verifying S3 readiness. Schema setup is separate. This preserves transaction boundaries without relying on staged bulk-loading behavior. It assumes all runtime writers use the same initialized mutex. Actual Snowflake concurrency and SQL compatibility require live verification.

Raw source text and normalized value text remain authoritative. NUMBER(38,12) is a provisional landing projection. Overflow and excess scale produce explicit quarantine rows and null numeric projections. A RAW load can succeed with reported quarantine counts. Later analytical publication must resolve those projections.

Snowflake connector 5.2.0 failed to import because Windows application control blocked its native core DLL. The project pins 4.8.1, which imports, and explicitly requests JSON result sets because the optional Arrow extension is also blocked. No application-control policies were changed.

The uploader and loader buffer local batches and target modest demonstration volumes. The loader requires the local archive as well as verified transferred objects. Multipart transfer, remote-only loading, and external-stage COPY remain later optimizations. SDK request shapes and transaction doubles do not establish real-service compatibility.

Terraform is absent on this host. Terraform fmt/validate and provider resolution remain pending. No AWS or Snowflake resources were created and no cloud charges were incurred.

## First live run prerequisites

Complete live FRED/SEC validation, idempotency checks, actual tag review and numeric profiling with locally configured credentials. Configure an approved AWS profile and a dedicated private bucket, plus Snowflake key-pair authentication and dedicated database/warehouse/role. Review the actual account/region cost estimate and obtain authorization before provisioning or paid execution.

The [cloud integration guide](cloud-integration.md#first-controlled-demonstration) gives the controlled sequence, required privileges and teardown procedure. The implementation is ready for that review and local preparation. Live service readiness remains conditional on those checks.
