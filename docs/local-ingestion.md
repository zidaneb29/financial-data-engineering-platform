# Local ingestion

The separate transfer and load commands are described in [cloud integration](cloud-integration.md). Ingestion-only installation uses requirements.txt and does not import cloud SDKs.

Run the CLI from the repository root with Python 3.11 or 3.12 and install `requirements.txt` for ingestion or `requirements-dev.txt` for ingestion and tests. The FRED and SEC universes, minimum dates, and SEC forms are in [source_scope.toml](../config/source_scope.toml).

## Configure and run

Set the credentials in your local shell or through a local environment runner. The CLI reads environment variables. Use [.env.example](../.env.example) as a reference.

| Variable | Value |
| --- | --- |
| `FRED_API_KEY` | Your application key from the [FRED API key page](https://fred.stlouisfed.org/docs/api/api_key.html) |
| `SEC_USER_AGENT` | An application or organization name followed by a real monitored contact email, per [SEC fair access](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) |
| `FIN_DATA_DIR` | Local archive root. Defaults to the ignored directory `.local/data`. |

Sample PowerShell commands after configuration.

```powershell
.\.venv\Scripts\python.exe -m ingestion fred --fred-series FEDFUNDS --mode backfill --start 2024-01-01 --end 2024-06-30
.\.venv\Scripts\python.exe -m ingestion sec --sec-issuer MSFT --mode backfill --start 2024-01-01 --end 2024-06-30
.\.venv\Scripts\python.exe -m ingestion all --mode incremental
```

Use `fred`, `sec`, or `all`. Select individual series or issuers with the repeatable flags. SEC accepts configured tickers and zero-padded CIKs. Omit selection flags to ingest the full configured source. Bounds are inclusive and start dates are clamped to each source's configured minimum. The default end date is today. FRED's request snapshot date is today even when the observation window ends in the past. SEC bounds filter fiscal period end. A later filing can still be retained when it supplies comparative facts in that window.

The exit status is 0 if every selected entity committed, 1 on a partial or failed run or unavailable writer lock, 2 for invalid arguments, and 130 on keyboard interruption. Missing source configuration fails its selected entities independently. Logs emit JSON events on stderr, including entity and run outcomes, processing durations, error codes, and normalized record counts.

## Storage and observations

```text
.local/data/
  raw/<source>/<entity>/<endpoint>/<sha256>.json
  processed/<source>/<entity>/<run-id>/<dataset>.jsonl
  metadata/batches/<source>/<entity>/<sequence>.json
  metadata/runs/<run-id>.json
```

Raw files are response body bytes after HTTP content decoding. Identical bodies for an entity and endpoint share one object. Manifests record the date window, request parameters safe for logging, endpoint, retrieval time, object key and SHA-256, expected normalized files, schema version, and counts. Read processed files through successful manifests in sequence order. Files left by an interrupted attempt have no commit marker and are ignored. A run journal contains failed and successful outcomes even when only some entities committed.

Phase 2A writes schema 2 manifests with normalized-file SHA-256, byte sizes, row counts and a canonical manifest checksum. Readers validate complete batches before returning them. Version 1 source artifacts remain readable with their original integrity limitations. See the [loader contract](cloud-loader-contract.md) for validation, sequence reservations and compatibility.

Dates are ISO date strings and timestamps are UTC ISO strings. Financial values use JSON strings containing exact decimal values. Missing data uses JSON null. All processed rows include `source`, `dataset`, `key`, `fingerprint`, `ingestion_timestamp`, `object_key`, and `source_row`. The source row is a zero-based index into the associated page or columnar result. For Company Facts it indexes the array at the associated namespace, tag and unit. The fingerprint hashes the normalized business fields. Raw snapshots and versioned manifests remain the source for request-level auditing.

| Dataset | Fields and versioning |
| --- | --- |
| FRED `observations` | Series ID, observation date, exact value, missing indicator, units, frequency and seasonal adjustment. Provenance includes the requested snapshot date, returned real-time interval, and series metadata object. Each change creates an event for the series/date, including a reversion. Unchanged observations remain traceable in the new manifest and raw page. |
| SEC `filings` | CIK, accession number, filing date, report date when available, form, primary document, amendment flag, and available metadata such as acceptance timestamp, file number, and XBRL flags. Blank report dates retain a null and use the filing date for initial inclusion. |
| SEC `facts` | CIK, accession number, namespace, tag, mapped metric, source unit, normalized unit, start date when present, end date, fiscal year and period, form, filing date, exact value, amendment flag, duration class, and optional frame. `filing_matched` and `selection_eligible` capture the join at first ingestion. A later selection checks the then-available filing metadata again. |

## Incremental updates and recovery

FRED reads contiguous coverage from successful request windows. It starts with the configured lower bound, fills gaps even if they exceed the lookback, and overlaps the most recent 730 calendar days by default. Set `--lookback-days` to adjust the overlap. Use a full backfill periodically for older revisions. Native frequency and calendar gaps are preserved. A true missing observation has a null value and a missing flag. A zero remains `"0"`.

EDGAR serves complete current Company Facts and current plus archived submissions. Both modes refresh and normalize the selected history, then append newly seen filing or fact variants. The CLI follows archive references when their last filing date can overlap the requested scope. This catches amendments and source corrections to older periods without a filing-date watermark. It also means repeated SEC runs download the relevant responses again. Unchanged normalized facts do not create additional rows.

Requests pace sequential calls per provider at one request per second for FRED and two for the SEC across selected entities. Run a single invocation per data root and budget any separately run processes against provider limits. Retries use up to four attempts, exponential backoff with jitter, and honor `Retry-After` on retriable statuses when the delay is at most 60 seconds. Longer delays stop further requests to that provider until the cooldown expires within the invocation. If rerunning manually, wait for the provider's cooldown first. Permanent HTTP failures, FRED error envelopes, TLS validation errors, and invalid payloads fail the entity. For SEC 403, verify the declared contact and outbound network before rerunning. [FRED errors](https://fred.stlouisfed.org/docs/api/fred/errors.html) · [SEC fair access](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)

The writer flushes a temporary file in the destination directory, atomically replaces the final path, and publishes the success manifest last. Replacement has bounded retries for transient Windows sharing and access errors. On the next invocation, an interrupted journal is reconciled against committed manifests before starting new work. A partial batch is fetched again when its entity is selected again. Previously committed batches remain readable. This design targets process interruption on a local filesystem. Crash leftovers can occupy disk space and are excluded from readers.

Counts distinguish validated rows received, rows written, exact repeats suppressed, and revisions or changed candidates relative to previously committed data. SEC's revision count can include a changed value for an existing tag/unit/period in a different accession. It is not evidence of a confirmed restatement. Unsupported units, missing concepts, same-key conflicts and unmatched facts remain inspectable. Manifest diagnostics count conflicting fact keys and unmatched rows for each SEC fetch.

## SEC candidate selection

The [concept map and allowed units](data-contracts.md#sec-edgar) cover US-GAAP aliases for the initial metrics. The code retains multiple tags and source units. It recognizes USD for amounts and USD per share for EPS, and does no currency conversion. Period classification uses dates and filing form to distinguish instants, likely standalone quarters, likely annual periods and year-to-date durations. It preserves unusual durations and fiscal labels without inferring fiscal comparability. A quarter may be in a later filing, and an annual report may contain historical comparative values.

- Use the accession and form to distinguish original filings and amendments. Filing dates and accession numbers provide provenance. A changed comparative figure or the presence of an amendment alone does not verify a restatement.
- Use `ingestion.sec.select_period_candidates` with normalized facts and filings. It checks CIK, accession, filed date, form, unit, and period shape, groups by issuer, metric, unit and exact dates, then ranks by filing date. Original mode takes the earliest non-amended candidate filed for the same report period. Default mode takes the latest eligible date up to `filed_through`. Tied candidates with conflicting values return an ambiguity and no selected value. Review aliases and financial-sector revenue definitions before building cross-issuer analytics.
- Use `ingestion.sec.read_snapshot` on a successful manifest to reconstruct what its archived responses contain, including unchanged rows. This is how to evaluate a specific observed snapshot or exclude a fact that disappeared from a later response. For cumulative local history, use the committed JSON Lines. `observed_through` limits those records to their local first-observed UTC timestamp. Filing date alone cannot reconstruct the historical state of the SEC API, same-day release order or XBRL facts omitted from current Company Facts. Issuer-specific extensions and facts with nonstandard contexts require filing-level XBRL.

For current available candidates, use `ingestion.sec.select_snapshot_candidates`. It chooses the latest validated snapshot, or the most recent one completed by observed_through, and returns the selected scope. An explicit manifest selects a historical snapshot. Its original flag preserves the established original-filing candidate rule within that snapshot. Cumulative history passed directly to select_period_candidates remains a query over historical candidates and can include values absent from a newer snapshot.

## Verification

The [Phase 2C audit](phase2c-validation.md) verifies live DGS10/MSFT ingestion, source comparisons and idempotent replay. It also records real-data cloud simulation results and remaining live cloud checks.

Phase 2B expanded the complete suite to **122 passing offline tests**. See the [Phase 2B report](phase2b-report.md) for the current combined results and service-verification limits.

Phase 2A passed **80 offline tests** on Python 3.11.9. See the [hardening report](phase2a-report.md) for the current integrity and snapshot-selection results. The earlier Phase 1 verification below is retained as historical evidence.

The [Phase 1.5 audit](phase15-audit.md) records the November 19, 2026 revalidation, missing live configuration, precision checks and expected loader interface.

On November 17, 2026, two consecutive runs each passed **38 offline tests** on Windows with Python 3.11.9 and pytest 8.4.2. `pip check` reported no broken requirements. Coverage includes mocked HTTP statuses and delays, FRED pagination and revisions, SEC archive traversal and amendments, multi-issuer failure isolation, atomic publication, interrupted-run reconciliation, and archived snapshot replay. In the restricted agent environment, pytest's default sandbox temporary directory denied atomic replacement. The passing runs used fresh test directories under the repository.

```powershell
$testRoot = '.local/phase1-tests-' + [guid]::NewGuid().ToString('N')
.\.venv\Scripts\python.exe -m pytest --basetemp $testRoot
```

Both live API configurations were absent. FRED authenticated requests were therefore untested. The SEC browser probe returned no payload or HTTP status, reproducing the Phase 0 symptom. Direct lookup and curl inside the sandbox failed during DNS resolution before any HTTP response. A direct transport probe outside the sandbox successfully resolved the host, connected to port 443, and completed TLS 1.3. This isolates the restricted-shell failure from host connectivity and leaves the browser-specific failure unresolved. EDGAR HTTP status, identifying header acceptance, and live response parsing still require an opt-in run with a locally configured contact.
