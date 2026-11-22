# Phase 6 financial analytics dashboard

Streamlit reads the existing DuckDB publication in read-only mode. Each UI rerun opens and closes its connection. The dashboard has no ingestion, credential, cloud, or write path. The supported dbt schema prefix is `fdep` from the local profile.

The current interface presents Economic Trends, Company Performance, and How the Data Works. See the [historical dashboard guide](dashboard-history.md) for the real dataset, selection rules, default database order and exact rebuild commands. The setup and verification below record the earlier fixture and Phase 3B dashboard.

## Run locally

Use Python 3.11 or 3.12 from the repository root. With a published database, install only the dashboard requirements.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dashboard.txt
.\.venv\Scripts\python.exe -m streamlit run dashboard/app.py --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false
```

Open the localhost address printed by Streamlit. The default publication is `.local/phase5/verification/analytics.duckdb`. If it is absent, install `requirements.txt` and `requirements-dbt.txt` in the same environment and use the existing Phase 5 host runner:

```powershell
.\.venv\Scripts\python.exe -m orchestration.local smoke .local/phase5/verification
```

That fixture includes all six configured series and twelve selected issuer snapshots. Its values are synthetic, and the UI identifies the fixture archive. Some series have a single recorded date and one issuer has an empty selected snapshot. To use an existing publication, set the environment variable before starting the app:

```powershell
$env:FDEP_DUCKDB_PATH = '.local/phase4-evidence/phase3b.duckdb'
.\.venv\Scripts\python.exe -m streamlit run dashboard/app.py --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false
```

The optional Phase 3B replay has 23 real DGS10 observations and 25 published Microsoft facts from a bounded archive. Warehouse commit timestamps reflect local replay. The scope seeds still show all configured entities and the UI reports unavailable selections explicitly.

## Reading each view

| View | Relations | Interpretation |
| --- | --- | --- |
| Economy | `series_scope`, `fact_economic_observations`, `stg_fred_observations` | One series and native unit/seasonal context per chart. Markers show numeric observations only, with no reindexing, gap filling, or derived growth. The table flags source missing values and quarantined numerics. Dates absent from the publication have no rows or markers. Recorded revision history is committed staging history and can include rows beyond a dbt cutoff. It marks the published choice and exposes requested snapshot dates and returned real-time bounds. |
| Companies | `issuer_scope`, `sec_selected_snapshots`, `sec_financial_candidates`, `fact_company_financials` | Explore one issuer, taxonomy/tag, unit and dbt period class at a time. YTD figures are further isolated by exact calendar duration. Source FY/FP are filing labels. Check exact start/end dates, including different fiscal calendars. Earlier filings, latest-date ties and unpublishable numeric projections are visible among eligible candidates from the selected snapshot. Amendments are identified by form. A change alone does not confirm a restatement. |
| Pipeline | `stg_batches`, `stg_batch_objects`, `sec_selected_snapshots`, `OPS.BATCH_LOAD` | Counts describe committed local batches, requests, normalized changes, snapshot members and quarantined records. Source observation and warehouse commit times have separate columns. Inspect run and batch identity, archived object keys and checksums, and selected SEC snapshot windows. Root-cause diagnosis of failed attempts or scheduler health requires orchestration logs. |

Source value text is preserved in tables and hover details. Chart coordinates are numeric approximations for display. Published points and eligible candidates follow the existing [dbt selection rules](phase4-dbt.md#time-grain-and-provenance). See the [source contracts](data-contracts.md) for metric definitions, source attribution, and access details. Full FRED vintage reconstruction and SEC filing-level restatement confirmation require additional source evidence.

Phase 7 places the three views in tabs and shows archive origin and read-only database status above them. One valid observation displays its exact source value in a metric. Two valid observations appear side by side with source dates. Larger selections use markers with day-level labels for daily FRED and SEC period ends, and month/year labels for monthly and quarterly FRED. Hover and lineage tables retain exact dates. Missing and quarantined values have no numeric marker.

The Pipeline tab highlights committed volume by source, selected snapshots and quarantine counts. Expandable sections retain reconciliation, batch evidence and selected snapshots. Batches marked with the fixture archive namespace explicitly label synthetic units, adjustments, keys and checksums. Genuine archives display their stored metadata and recorded digests. Dashboard rendering does not run an archive hash check.

## Verification


- Ran Streamlit AppTest against the Phase 5 publication and the existing Phase 3B replay. Economy, Companies and Pipeline rendered without app errors. The corresponding ledgers showed 21 and four committed batches, and the selected SEC snapshot counts were twelve and one.
- The dashboard regression uses the Phase 5 host runner to build a fresh offline publication. dbt passed all 43 nodes, including all 31 data tests.
- Phase 5 Airflow runtime execution remains unverified on this Windows host. The app reports committed warehouse evidence and makes no claim about live scheduler health.

- Started the documented Streamlit command on loopback with a smoke-test port. The health endpoint returned `ok` and the application shell returned HTTP 200. The smoke server was stopped afterward.
- `python -m pytest --basetemp=.local/phase6-acceptance` reported 136 passed and one skipped. The skip was the existing Airflow DAG import test.
