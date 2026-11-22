# Phase 4 dbt transformations

Phase 3B verified the transactional RAW landing path. Its private evidence is under .local/phase3b-live, including demonstration.md and teardown.md. The four committed batches comprised 91 changes, 136 SEC snapshot members and eight request references to four unique raw objects. The Snowflake demonstration was torn down, the dedicated S3 bucket was emptied, and the Terraform-managed AWS resources were retained.

## Plan and acceptance criteria

| Work | Acceptance criteria |
| --- | --- |
| Establish a dbt Core project on DuckDB | A credential-free fixture built from the RAW/OPS DDL passes dbt build. A scope regression checks all six series and twelve issuers against ingestion configuration. |
| Stage committed records and lineage | Batch counts reconcile to the ledger. Each staged record resolves to its batch request and archived object. Exact decimals, original value text, missing flags and quarantines survive. |
| Publish FRED and SEC views | Fixed cutoffs reproduce earlier states. Same-day FRED revisions are deterministic. SEC facts use one explicit member set per issuer and retain filing attribution. Ambiguous and incompatible financial facts are excluded from the published fact. |
| Prepare Snowflake parity check | Parse the Snowflake target locally and document a bounded live check with approval, cost, reconciliation and cleanup. Live acceptance requires a separately approved successful Snowflake build. |

DuckDB executes the same models and data tests as Snowflake. Adapter-specific SQL is limited to JSON scalar extraction and timezone-aware timestamp types. The project uses views and rebuilds their definitions when cutoff variables change. dbt's default schema naming isolates the outputs under the target prefix, such as fdep_staging and fdep_analytics.

## Run locally

From the repository root on PowerShell, with Python 3.11 and a new fixture path:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -r requirements-dbt.txt
New-Item -ItemType Directory -Force .local/phase4-profiles | Out-Null
Copy-Item dbt/profiles.example.yml .local/phase4-profiles/profiles.yml
$env:FDEP_DUCKDB_PATH = '.local/phase4.duckdb'
.\.venv\Scripts\python.exe -m scripts.phase4_fixture $env:FDEP_DUCKDB_PATH
.\.venv\Scripts\dbt.exe build --project-dir dbt --profiles-dir .local/phase4-profiles --target local
.\.venv\Scripts\dbt.exe docs generate --project-dir dbt --profiles-dir .local/phase4-profiles --target local
.\.venv\Scripts\python.exe -m pytest --basetemp=.local/phase4-pytest
```

The fixture command requires a new file. Choose another path to start from scratch. Ordinary pytest runs remain credential-free. The executing dbt regression skips when optional dbt dependencies are absent. Scope consistency still runs. The synthetic fixture gives every configured entity an input. Production coverage depends on which successful batches were loaded.

## Time, grain and provenance

| Relation | Grain and selection |
| --- | --- |
| stg_batches | One committed load. Source observation time is the manifest completion timestamp. The warehouse commit timestamp and source manifest sequence are separate fields. Use one authoritative archive sequence per source/entity in a target. |
| stg_batch_objects | One request per committed batch and request index. Includes archive namespace, object ID, exact stored key, hash and retrieval timestamp. Prefix a model row's object key with archive namespace and match within batch. |
| stg_fred_observations | One recorded change per batch, series and observation date. Carries source observation date, requested snapshot date, returned real-time bounds, native units, missing status, and observation and metadata object keys. |
| fact_economic_observations | One recorded change per series and observation date. Filter to eligible observation and snapshot cutoffs, then prefer latest snapshot date and highest manifest sequence. Explicit missing and quarantined values survive selection as null numeric values with separate flags. |
| stg_sec_members, stg_sec_filings, stg_sec_facts | All captured members, including unchanged facts and superseded accessions. Filing versions are keyed by batch, CIK and accession. Company Facts retain exact source units, dates, frame and fiscal labels, accession and raw row provenance. |
| sec_selected_snapshots | Highest eligible manifest sequence per CIK, selected from the ledger even when membership is empty. The requested window remains visible, and records from earlier batches outside the selected window are not carried forward. |
| sec_financial_candidates | Reporting-period facts matched within the same batch, CIK, accession, form and filing date. The fact end must equal the filing report date. Carries filing object, primary document, acceptance timestamp text when supplied, and original fact lineage. |
| fact_company_financials | One unambiguous fact per CIK, taxonomy, tag, normalized unit, period class and exact start/end. Rank by filing date within that grain. If multiple candidates share the winning date, or its numeric projection is quarantined, the grain has no published value. Candidates remain queryable. |

Values use the RAW loader's checked decimal(38,12) projection. Source text preserves all digits, including values outside the projection. Reconciliation also counts quarantined entries. A latest amendment can supersede an original only at the same concept, unit and exact dates. Source fiscal labels describe filing metadata and should not serve as keys for matching fact periods. A reported standalone quarter, YTD context, annual duration and instant remain distinct. Historical comparative facts, unsupported period classes and unmatched filings remain in staging. Metric labels such as revenue are descriptive groupings. Cross-tag substitutions, cross-sector ratios, fiscal growth joins and derived Q4 are outside the published contract.

Set these optional dbt vars with --vars. Quote values in the YAML or JSON mapping. Defaults use every committed batch and every filing date in the selected snapshots.

| Variable | Inclusive bound |
| --- | --- |
| observed_through_utc | Local source observation cutoff for both providers, UTC YYYY-MM-DDTHH:MM:SSZ. A later warehouse backfill can populate a view rebuilt with the same source cutoff. |
| fred_snapshot_through | FRED requested vintage date, YYYY-MM-DD. Apply alongside the observation cutoff to exclude later captures when reproducing past knowledge. |
| sec_filed_through | SEC filing date, YYYY-MM-DD. Applied inside the selected snapshot. Combine with the observation cutoff for historical availability. Acceptance time is retained as evidence and date-level filing filters are inclusive. |

SEC views reflect what the archive observed within the captured scope. FRED RAW stores normalized changes, so the mart answers which change the archive had recorded rather than reconstructing every unchanged historical snapshot. Exact historical FRED vintage studies, including out-of-order vintage retrievals, require page-level snapshot replay or further vintage ingestion. Load all preceding changes for a FRED scope before relying on historical queries. Keep both source and warehouse timestamps when exporting historical evidence.

## Bounded Snowflake verification pending approval

The [Phase 7 parity runbook](phase7-snowflake-parity.md) specifies the executable local archive preflight, Snowflake load and row comparator for the four preserved batches. It supersedes the proposed execution steps below.

1. In a separate local virtual environment, install requirements-dbt-snowflake.txt. The Snowflake adapter has connector constraints that differ from the ingestion environment. Use the included profile template with environment-bound account, user, role, warehouse, database and isolated schema prefix. Local target parsing uses dummy profile fields and opens no warehouse session.
2. Before requesting approval, confirm the intended account, region, credit balance, credit rate and warehouse billing terms. Estimate one X-Small warehouse with a short auto-suspend and one planned execution window of up to 10 active minutes. At Phase 3B's reviewed $3 per credit and one credit per hour, that budget is approximately $0.50 compute before restarts, storage, cloud services and taxes. Recalculate for actual terms and include a contingency within the project budget. A 120-second statement timeout helps bound a query. It does not cap the entire build.
3. With separate approval for lifecycle and cost, use a dedicated test database and schemas. Grant the transform role warehouse/database USAGE, RAW and OPS USAGE and SELECT, and creation/write privileges confined to its output schemas. Use the existing validated loader for the four preserved Phase 3B batches, or pre-load the identical bounded RAW/OPS input locally and in Snowflake for strict parity. AWS reuse or modification requires its own approved scope. Run a single-threaded dbt build with a query tag, then reconcile staging counts, lineage, selected dates, copied 38-digit decimals and mart output against the same DuckDB inputs. Include the synthetic adversarial fixture if the live approval covers it. Capture dbt artifacts and query IDs in the ignored evidence directory.
4. Stop after the reviewed run, capture observed credit use and outcome, suspend compute, remove the dedicated Snowflake resources under the approved teardown, and verify absence. Recheck metering after its reporting delay. Preserve local archives, Phase 3B evidence, and Terraform resources.

## Observed verification

| Command | Result |
| --- | --- |
| python -m pytest --basetemp=.local/phase4-full | 130 passed, including scope synchronization and three dbt builds testing the default, historical source, and independent filing/vintage cutoffs. |
| dbt build --project-dir dbt --profiles-dir .local/phase4-profiles --target local | 43 nodes passed on the synthetic inputs, comprising 10 models, two seeds and 31 data tests. |
| dbt docs generate --project-dir dbt --profiles-dir .local/phase4-profiles --target local | Generated the manifest and catalog for the DuckDB target. |
| python .local/phase4-evidence/replay_phase3b.py followed by dbt build --target local using the replay database | Four verified batches replayed locally through the loader test double. All 43 nodes passed. Outputs included 23 DGS10 observations and 25 Microsoft financial fact rows from the selected SEC snapshot. |
| dbt parse --project-dir dbt --profiles-dir .local/phase4-profiles --target snowflake --no-partial-parse | Parsed with dbt-snowflake 1.10.6 using dummy profile fields. Snowflake SQL execution remains pending. |

The local replay uses the original reviewed manifests and source files as read-only input. It reconstructs the warehouse commit ledger locally, so its simulated warehouse commit timestamps differ from Phase 3B. The replay database and build evidence are under the ignored .local directory.
