# Phase 1.5 validation and warehouse readiness

Audit date is November 19, 2026. The audit inspected the project instructions, ingestion guide, architecture, contracts, roadmap, FRED and SEC clients, shared HTTP and numeric handling, CLI, pipeline coordinator, local storage, and offline tests.

Subsequent Phase 2A work addresses the implementation gaps recorded below. See the [hardening report](phase2a-report.md) and [current loader contract](cloud-loader-contract.md). The findings in this audit describe the pre-hardening implementation.

## Live validation outcome

Neither `FRED_API_KEY` nor `SEC_USER_AGENT` was populated in the process, Windows user environment, or Windows machine environment. `FIN_DATA_DIR` was also unset and the repository contained no `.env`. The default live archive root `.local/data` was absent. Existing local directories contained Phase 1 test artifacts and pip temporary files. Existing test snapshots were treated as mocked data.

| Requested check | Outcome |
| --- | --- |
| Live FRED observations, units, frequency, missing values and decimals | Pending local key configuration |
| Live FRED raw/normalized persistence, replay and incremental manifests | Pending local key configuration |
| Live SEC submissions and Company Facts HTTP statuses, response metadata and identifying header | Pending local User-Agent configuration |
| Live SEC values, namespaces, tags, fiscal periods, accessions and amendments | Pending local User-Agent configuration |
| Live SEC persistence and replay idempotency | Pending local User-Agent configuration |
| Verified mappings against retrieved live payloads | None in this audit |

No source HTTP requests were issued in this audit. There are no new HTTP status codes or response headers to report. The November 17 transport check remains prior evidence only. It established DNS, TCP and TLS connectivity outside the restricted sandbox, while the sandbox lookup failed before HTTP. The browser probe supplied no HTTP status. Those observations do not identify the cause of the browser failure or establish SEC HTTP acceptance.

Configure values in the same local PowerShell process that will run ingestion. These commands prompt without putting the entered values into command history.

```powershell
$env:FRED_API_KEY = Read-Host 'FRED application API key' -MaskInput
$env:SEC_USER_AGENT = Read-Host 'Application name followed by monitored contact email'
.\.venv\Scripts\python.exe -m ingestion fred --fred-series FEDFUNDS --mode backfill --start 2024-01-01 --end 2024-06-30
.\.venv\Scripts\python.exe -m ingestion sec --sec-issuer MSFT --mode backfill --start 2024-01-01 --end 2024-06-30
```

Request an application key through the FRED key page linked in the ingestion guide. The CLI reads the environment directly. A saved `.env` requires a local runner that loads it. Inspect an existing data root before executing these commands and select a fresh ignored `--data-dir` for an isolated validation if necessary. Repeat identical commands to check zero newly written normalized rows when the source payload is unchanged. An incremental FRED run must additionally inspect the requested window and contiguous coverage.

The HTTP client currently discards success status and response headers after JSON decoding. A live audit will need a sanitized response hook or probe to record actual status, content type, body size, retrieval time and permitted cache metadata without printing full request URLs, authorization values, or the SEC contact. Merely finding a success manifest cannot establish the exact HTTP status.

## Mapping assessment

These are implementation findings from inspection and mocked tests. They remain unverified against live filings.

| Mapping or rule | Implemented behavior and remaining validation |
| --- | --- |
| Revenue | Three US-GAAP aliases are retained. Selection groups aliases under one metric. Check accounting scope and bank revenue definitions before comparing companies. |
| Net income | NetIncomeLoss and ProfitLoss map to one metric. Verify entity and noncontrolling-interest scope in the underlying statements. |
| Assets and liabilities | Expected to be instants with USD units. Duration-shaped candidates are retained but excluded from selection. |
| Operating income, operating cash flow and capital expenditure | Duration concepts retain their original signs and periods. Cash flow often represents year-to-date totals. No standalone-quarter derivation is implemented. |
| EPS | Basic and diluted remain separate metrics. USD/shares and USD-per-shares normalize to the same unit. Check split adjustments and retrospective comparatives at filing level. |
| Fiscal periods | Source fy and fp are retained. Date ranges drive heuristic classification. These labels can describe the reporting filing while the fact represents an earlier comparative period. |
| Period classification | Annual requires 350–380 inclusive days in a 10-K variant. Quarter requires 70–110 days. Selected 10-Q durations are marked year-to-date. Short years and other durations remain candidates outside ordinary selection. |
| Conflicts and overlap | Exact repeats are suppressed. Different values for the same fact key remain distinct. Latest/original selection exposes tied conflicting values as ambiguous. It does not prove alias equivalence when values agree. |
| Amendments | Form suffix and accession retain amendment identity. Original mode selects an earliest non-amended same-report-period candidate. This establishes an available candidate, subject to the source's historical coverage. |
| Extensions and restatements | Custom issuer taxonomies require filing-level retrieval. A changed value or amended form requires filing evidence before classification as a confirmed restatement. |

The missing-metric diagnostic checks whether a mapped tag exists anywhere in Company Facts. It does not establish that an eligible value exists in the requested period. The unmatched-fact diagnostic and selection checks must also be reviewed.

## Numeric precision

The parser reads JSON fractional numbers through Decimal and integer numbers through Python integers. Normalization emits exact decimal text, converts numerical zero to `"0"`, and drops trailing fractional zeros. Raw bytes preserve the original lexical representation. There is no float conversion in this path.

An additional local probe passed five exact equality checks covering zero, a 39-digit integer, a decimal with 38 fractional digits, scientific notation at 1e-20, and a negative decimal with trailing zeros. These are synthetic precision checks. Live source magnitude and scale distributions remain unknown.

The local implementation can represent numbers beyond Snowflake's maximum 38-digit NUMBER precision. Phase 2 must profile actual values, choose per-field precision and scale, and reject or quarantine overflow or rounding instead of silently casting. Preserve the original decimal text alongside warehouse conversion results. Current numeric magnitude validation permits exponents up to absolute adjusted exponent 1000 and does not impose a warehouse-compatible precision bound.

## Expected loader interface

The following defines the intended Phase 2 boundary. No warehouse loader was implemented.

1. Discover only `metadata/batches/<source>/<entity>/<sequence>.json`. Validate schema version 1, success status, source/entity identity, date bounds and all referenced relative paths. Reject path traversal or paths resolving outside the selected archive root. Existing LocalStore readers assume trusted paths and do not enforce those checks.
2. Derive the load identity from the archive namespace plus source, entity and run_id. Record the exact manifest byte hash in the warehouse ledger and treat a changed hash for an already loaded identity as an error. The manifest's relative path is useful for lineage but sequence alone is insufficient across roots.
3. Read only the raw objects referenced by the manifest and verify their SHA-256 using `LocalStore.read_object`. Keep object hash, endpoint, request parameters and retrieval timestamp. An unchanged response may be referenced by many batches.
4. Read only normalized paths in the manifest and preserve dataset, key, fingerprint, lineage and exact value text. The normalized object is a change stream. An empty mapping is a valid duplicate-only or zero-record success. Reconcile total rows with counts.written and confirm retrieved equals written plus duplicates.
5. Validate row schemas, source/entity identity, raw object membership and reconstructable business fingerprints before loading. Add per-file checksums and per-dataset row counts at the ingestion/transfer boundary before relying on transferred JSON Lines. Current manifests provide raw checksums and aggregate counts but lack normalized file checksums, byte sizes and dataset counts.
6. Use a warehouse transaction to commit rows and the successful load-ledger entry together. Retry failed loads using the same manifest identity. Serialize per-entity loads and preserve ingestion sequence independently of warehouse load time.
7. Use source, entity, dataset, run_id and normalized row ordinal for ingestion-event identity. FRED revisions and reversions require event identity in addition to date/key/fingerprint, since a prior value can recur. SEC candidates require accession, namespace, tag, source unit, dates and fingerprint to preserve conflicting variants.
8. Carry committed batch and object relationships into the warehouse. Rows currently inherit run identity from their containing manifest and processed path. Do not infer it from a row field that is absent.
9. Build latest views with explicit source snapshot and committed order rules. SEC cumulative JSON Lines retain earlier candidates even if the API later withdraws them. `read_snapshot` can reconstruct the current membership from one archived SEC batch. Preserve snapshot membership for latest-state and historical-as-observed views.

| Capability | Assessment |
| --- | --- |
| Completed entity batches | Supported through atomically published manifests, independently of the overall run outcome |
| Raw provenance and access | Supported with raw hashes and object/page metadata |
| Normalized history | Supported as manifest-referenced changes, with exact values and raw lineage |
| Avoid repeated warehouse loads | Requires the Phase 2 transactional load ledger described above |
| Partial ingestion recovery | Covered by offline interruption and failure-isolation tests |
| Detect revisions | New FRED values and SEC candidates are retained. Revision counters are diagnostics rather than an authoritative event classifier. |
| Integrity after disk or transfer corruption | Raw reads can verify hashes. Normalized file integrity and strict manifest validation require hardening. |

Additional storage limits were found during inspection. `Batch.archive` reuses an existing content-addressed file without verifying its bytes. The manifest sequence is calculated from file count, so deleting a prior manifest can cause a later filename to be reused. Current operation therefore assumes retained manifests and an intact local archive. Before warehouse transfer, validate raw files, preserve manifests immutably, and harden allocation if deletion or repair must be supported. The writer lock applies to one data root. Separate roots do not coordinate the provider-wide rate limit.

## Verification and recommendation

The complete offline suite passed with **38 passed, 0 failed** on Python 3.11.9 and pytest 8.4.2. The run used a fresh ignored `.local/phase15-tests-<uuid>` directory. `pip check` found no broken requirements. Existing tests exercise repeated ingestion, historical revisions, retained amendments and conflicts, failure isolation, interrupted writes and recovery. They provide mocked evidence for duplicate prevention and preservation of committed rows during failure.

The inspected logging path omits the FRED key and SEC contact, stores sanitized FRED request parameters, and suppresses request exception URLs. Existing redaction tests passed. Git ignore checks confirmed exclusions for environment files and local generated artifacts. No configured secrets were available to test against a live error response.

The project can proceed with local Phase 2 interface design and offline tests using this contract. The live-data readiness gate remains open. Complete one live FRED and SEC validation, repeat both runs, record safe HTTP metadata, inspect actual mappings and numeric ranges, and address the transfer integrity checks before treating the ingestion output as a verified warehouse feed. This audit changed documentation only and used fresh offline test artifacts.
