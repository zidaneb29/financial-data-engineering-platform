# Phase 2C source validation

The controlled live run on November 20, 2026 succeeded for FRED DGS10 and SEC Microsoft. Its original artifacts were independently revalidated, and an isolated copy was exercised with simulated cloud services. The production ingestion, transfer and loading implementations were retained because this review found no demonstrated ingestion defect.

## Verified live archive

The supplied archive is .local/live-validation-66995445b3f349a2a380442d675db077. Acquisition timestamps run from 2026-11-21 00:49:20 to 00:49:34 UTC, corresponding to November 20 at 19:49 EST. Both source ingestions ran twice. All eight completed HTTP outcomes were 200 and returned JSON. Both SEC endpoint requests in each run recorded that the identifying User-Agent matched configuration.

Every HTTP body hash and size matches its archived raw object. Four unique raw objects represent eight request outcomes through content-addressed reuse. All four success manifests, raw checksums, normalized-file checksums, row fingerprints and run journals validated. The complete original artifact tree was hashed before and after review and remained unchanged.

| Source | First ingestion | Repeat ingestion | Numeric findings |
| --- | --- | --- | --- |
| FRED DGS10 | 23 observations for January 2024, including 21 values and 2 missing markers | 23 duplicates, 0 writes, 0 revisions | Daily, Percent, observed values 3.91–4.18, at most 2 fractional digits |
| SEC Microsoft | 61 financial candidates and 7 related filing records | 68 duplicates, 0 writes, 0 revisions | USD and USD/shares, at most 12 integer and 2 fractional digits |

FRED missing dates are January 1 and January 15. Their values remain null with the missing flag set. Observation dates span January 1–31 and successful request coverage advances to February 1. The second FRED summary contains no numeric rows because normalized output is a change stream. Its raw observations and metadata are byte-identical to the first run. That empty change profile does not indicate lost observations.

All 61 SEC candidates matched submissions by accession, form and filed date. The available source namespaces are dei, ecd, ffd and us-gaap. The selected financial records use nine us-gaap concepts representing revenue, operating income, net income, assets, liabilities, operating cash flow, property-and-equipment payments, and basic/diluted EPS. No missing mapped metrics, same-key value conflicts, unmatched facts or ambiguous selected groups were observed in this scope.

### Financial and fiscal-period checks

The 2024-06-30 annual period runs from 2023-07-01. Representative values below were traced to raw Company Facts and checked against Microsoft's 2024 annual financial statements. Monetary source values are dollars. The report presents monetary totals in millions and EPS in dollars per share. [Microsoft 2024 annual report](https://www.microsoft.com/investor/reports/ar24/index.html)

| Metric | Exact normalized value |
| --- | --- |
| Revenue | 245122000000 USD |
| Operating income | 109433000000 USD |
| Net income | 88136000000 USD |
| Assets at June 30 | 512163000000 USD |
| Liabilities at June 30 | 243686000000 USD |
| Operating cash flow | 118548000000 USD |
| Property-and-equipment payments | 44477000000 USD |
| Basic EPS | 11.86 USD/shares |
| Diluted EPS | 11.8 USD/shares |

The capex payment concept retains a positive payment magnitude. The financial statement shows that amount as an investing cash outflow. No sign change was introduced.

Classification yields 21 annual, 14 quarter, 14 year-to-date and 12 instant candidates. For March 31, 2024, the standalone quarter starts January 1, while year-to-date starts July 1, 2023. Assets and liabilities have no start date. These are distinct periods.

Later filings retain comparative 2024 values with their own 2025–2026 filing metadata. Source fy/fp labels describe the reporting context and must not replace fact start/end dates as the observation period. Seven related filings are therefore valid even though some report dates exceed the selected observation window.

Filed-through selection returns no groups before April 25, 2024, 16 groups on April 25, and 25 groups by July 30. Original mode selects 25 groups. Historical observation-cutoff queries resolve to the intended archived snapshot. The second snapshot retains all 68 members despite writing no additional historical changes.

No amended financial facts or amended filings were selected in this sample. Live amendment and withdrawal behavior therefore remains unsampled. Existing synthetic regressions cover those paths. Issuer-specific extensions, alias equivalence in other issuers, financial-sector revenue, and confirmed restatement classification still require their own filing evidence. The matching comparative values here do not establish a restatement.

### Loader and replay verification using live data

All four v2 batches passed prepare_batch with stable identities matching the original summary. All 82 nonmissing financial values across the first FRED and SEC observations fit NUMBER(38,12) exactly. No sampled value required quarantine. This supports that projection for this sample while leaving full-universe profiling open.

An isolated copy under .local/live-archive-audit-30059a2fd1ce4aa7a6edf22043803366 was transferred and loaded through MemoryS3 and MemoryWarehouse. Each batch was then transferred and loaded again. Replay produced zero additional uploads and successful warehouse-ledger replay.

| Simulated warehouse table | Reconciled rows |
| --- | --- |
| RAW.SOURCE_OBJECT | 4 |
| RAW.BATCH_OBJECT | 8 |
| RAW.INGESTION_RECORD | 91 |
| RAW.SEC_SNAPSHOT_MEMBER | 136 |
| OPS.BATCH_LOAD | 4 |

No numeric quarantine rows were produced. The largest source object is 4,938,072 bytes and passes the local 16 MiB loader text bound. Actual server binding and result fidelity for this payload remain live cloud checks.

The generated audit.json records source hashes, unchanged-original verification, revalidated batches and simulated transfer/load reports. No S3 or Snowflake service call was made. These results establish local contract and protocol readiness for the live sample.

All 19 original files, including both sequence reservation files, were accounted for. Each source retains last_reserved=2. After the review, the complete regression suite passed again with **127 passed, 0 failed in 48.48 seconds** on Python 3.11.9. pip check found no broken requirements. The earlier 27.60-second result below records the initial helper validation.

## Initial configuration-only check

Before the successful user execution, the checks below established missing credentials in the agent process and a working host transport path. They are historical observations, superseded for live-source success by the supplied archive above.

## Observed live-source results

| Check | Actual result |
| --- | --- |
| FRED_API_KEY | Absent from process, Windows user and machine environment |
| SEC_USER_AGENT | Absent from process, Windows user and machine environment |
| Repository environment file | Only .env.example was present |
| FRED live HTTP and ingestion | Configuration required. No API HTTP request or observation retrieval performed. |
| SEC live HTTP and ingestion | Configuration required. No API HTTP request or filing retrieval performed. |
| Sandbox source transport | Both host probes failed at DNS resolution with gaierror |
| Network-enabled host transport | Both api.stlouisfed.org and data.sec.gov completed DNS, TCP and TLS 1.3 on port 443 |

The transport checks sent no source API HTTP requests. They establish a usable host transport path, with API authentication, identifying headers and HTTP acceptance still unverified.

The actual validation command created the ignored directory .local/live-validation-3996af8b3cf9490c8eeff89580dc6e06. Its summary.json records configuration_required for both sources, zero complete HTTP responses and an exit code of 1. Its http-outcomes.json is an empty list. No financial snapshots were generated by that invocation.

## Secure Windows configuration and execution

Obtain an application key through your FRED account. The API requires users to supply their own key. Keep the key local. [FRED API keys](https://fred.stlouisfed.org/docs/api/api_key.html)

Run these commands in a local PowerShell window with network access. They work with Windows PowerShell 5.1 and PowerShell 7, mask entered values, and keep credentials out of command history. Values are scoped to that shell process. The SEC value contains the actual application name and the monitored contact email you enter.

~~~powershell
# Run from the repository root.
$fredSecret = Read-Host 'FRED application API key' -AsSecureString
$env:FRED_API_KEY = [System.Net.NetworkCredential]::new('', $fredSecret).Password
$secContact = Read-Host 'Monitored SEC contact email' -AsSecureString
$env:SEC_USER_AGENT = 'FinancialDataEngineeringPlatform ' + [System.Net.NetworkCredential]::new('', $secContact).Password
.\.venv\Scripts\python.exe -m scripts.validate_sources
~~~

The command prints the summary file location. Each invocation creates a fresh output directory and refuses to overwrite an existing one. Use --source fred or --source sec when only that source is configured. Existing ingestion archives and local configuration files are preserved.

The controlled FRED sample uses configured series DGS10 for January 2024. It provides a daily-rate sample where holiday missing values can be inspected if returned. SEC uses configured issuer MSFT for fiscal period ends in January–June 2024. The SEC API serves a full Company Facts document per issuer, so the normalized window limits processing while the raw response remains complete. Submissions history references are followed by the existing pipeline where needed. [FRED observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html) · [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

The runner performs two successful ingestion attempts per configured source, stopping a source after a failed attempt. Existing timeouts, bounded retries and one/two-per-second source pacing apply. Failure of one configured source does not establish failure of the other. A changed source record on replay is reported as source_changed_review_required. It does not automatically establish an idempotency defect.

## Evidence and verification artifacts

| Artifact under the new output directory | Purpose |
| --- | --- |
| summary.json | Source status, run IDs, comparison counts, manifests, batch identities, numeric profiles, selection diagnostics and local loader preparation counts |
| http-outcomes.json | Actual completed-response status, host/path, content type, byte count and body SHA-256. SEC also records whether the request User-Agent matched local configuration. |
| archive/raw/ | Original decoded response bodies, addressed by SHA-256 |
| archive/processed/ | Normalized changes, including source-object and source-row references |
| archive/metadata/batches/ | Validated v2 manifests, checksums, request windows and counts |
| archive/metadata/runs/ | Successful, partial and failed run evidence with sanitized error codes |

The HTTP evidence excludes query strings and request header values. It never records the FRED key or SEC contact. A request failing before a complete response has no completed-response entry. Inspect the run journal for its failure outcome. Preserve the complete validation directory for subsequent local verification. It remains excluded from Git.

For each committed batch, the runner compares every inspected normalized record to its indexed raw source record. FRED checks dates, exact value or missing marker, units and frequency. SEC checks accession, dates, form, fiscal labels and exact numeric value, plus filing column references. It profiles observed integer and fractional digits, reports NUMBER(38,12) conversion exceptions, prepares the S3 input contract without uploading, and invokes the existing loader's record preparation without connecting.

SEC checks reconstruct full snapshot membership, including unchanged candidates. Reports include source namespaces, mapped tags and units, period classes, fiscal labels, amendment counts, ambiguous selections, original candidate groups and historical snapshot identity. Exact filing-level meaning, confirmed restatements, bank revenue comparability and issuer extensions continue to require source filing evidence. These rules were preserved.

## Earlier financial and loader findings

No live values were available during the initial configuration-only check. The supplied archive now verifies the sampled dates, frequencies, tags and numeric distributions as recorded above. NUMBER(38,12) remains provisional for the complete source universe. Exact source text and quarantine remain necessary for values outside its bounds.

Local preparation and simulated cloud reconciliation have now passed on real source snapshots. Live S3 and Snowflake compatibility remains unverified.

## Tooling status and SQL assumptions

Snowflake connector 4.8.1 imports on this host. The optional Arrow extension remains blocked by Windows application control. The existing connection factory requests JSON results. Neither Snowflake authentication nor query-result retrieval was exercised.

Connector 5.2 is no longer installed and its earlier native core DLL is absent from the project environment. Its original blocked import remains historical evidence. This audit did not reinstall it, so its current compatibility is undetermined.

Terraform was not found on PATH or in the inspected user program and bundled runtime locations. Terraform formatting, provider resolution and validation remain pending in an environment with the CLI available.

The SQL contract retains a separate DDL bootstrap and an explicit DML load transaction. A pre-existing control row serializes cooperating writers, while the committed batch ledger supports replay. Documentation review confirms that DDL commits active transactions. Offline doubles still cannot validate actual Snowflake syntax, locking, parameter binding, detached transactions or rollback behavior. Those remain controlled cloud checks. [Snowflake transactions](https://docs.snowflake.com/en/sql-reference/transactions)

## Deployment recommendation

The complete offline suite passed with **127 passed, 0 failed** in **27.60 seconds** on Python 3.11.9 and pytest 8.4.2. The five new tests cover numeric profiling, raw FRED and SEC comparisons, snapshot selection, cloud-input preparation, missing-configuration behavior, safe output preservation and HTTP-evidence redaction with mocked responses. These tests provide no live-source verification.

The suite used a fresh ignored .local/phase2c-tests-<uuid> directory. pip check found no broken requirements, Python compilation succeeded, and the source-only command's help rendered successfully.

The sampled live-data gate is satisfied. Proceed to preparation of the first controlled cloud demonstration using these source scopes. Validate Terraform, review actual account/region costs, configure dedicated identities and resources, and obtain explicit deployment approval. Then run one FRED and one SEC scope through transfer/load, verify replay and actual Snowflake transaction behavior, and perform documented teardown. Broader issuer/indicator coverage and live amendment cases remain later validation work.

This audit created local validation helpers, tests and documentation. It made no cloud resource changes, activated no trials and changed no Git history.
