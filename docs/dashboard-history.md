# Rebuild the dashboard’s historical dataset

The dashboard prefers the full local DuckDB build, then the original archive sample, then the earlier Phase 3B replay, then the synthetic fixture if available. `FDEP_DUCKDB_PATH` overrides that order. Without a local publication, it opens the [public historical preview](public-preview.md). Keep downloaded and derived files under `.local/`.

## Bounded collection plan

Request observation dates and fiscal period ends from **2019-01-01 through 2025-12-31**, inclusive. Use a dedicated archive with one window and the [configured set](../config/source_scope.toml).

| Source | Plan | Estimated requests before retries |
| --- | --- | ---: |
| FRED | DGS10 and DGS2 daily, FEDFUNDS, CPIAUCSL and UNRATE monthly, GDPC1 quarterly. At most 5,394 observation dates across all six series, including holidays recorded as missing, at full page sizes. | 6 metadata requests and about 10 observation pages at 1,000 records per page |
| SEC EDGAR | MSFT, AAPL, NVDA, AMZN, JPM, GS, BAC, JNJ, PFE, WMT, XOM and CVX. Use 10-K, 10-Q and amendments. EDGAR sends complete Company Facts and the loader filters locally. Request only historical submissions files whose filing range can overlap the window. | 24 base requests plus the overlapping submissions files, estimated 0–12 additional requests |

Plan for under 2 MiB for FRED and roughly 50–150 MiB of SEC response bodies, with 1 GiB of local working space for the archive, temporary database and publication. SEC payload sizes and extra submissions requests vary by issuer. The existing transport paces FRED at one request per second and SEC at two, with up to four attempts per request. Do one sequential pass. Stop on a credential or provider access failure and resolve it before retrying. [FRED observations and vintage parameters](https://fred.stlouisfed.org/docs/api/fred/series_observations.html) · [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) · [SEC fair access](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)

## Capture and publish

Run from the repository root in the project virtual environment. Install `requirements.txt`, `requirements-dbt.txt` and `requirements-dashboard.txt`. Configure `FRED_API_KEY` with an existing application key and `SEC_USER_AGENT` with an application name followed by a monitored contact email. Phase 2C used process-scoped variables. In a fresh shell, use masked prompts and run the capture from that same shell. [Phase 2C credential setup](phase2c-validation.md#secure-windows-configuration-and-execution)

```powershell
$fredKey = Read-Host 'Existing FRED application API key' -AsSecureString
$secEmail = Read-Host 'Monitored email address for SEC EDGAR' -AsSecureString
try {
    $env:FRED_API_KEY = [System.Net.NetworkCredential]::new('', $fredKey).Password
    $env:SEC_USER_AGENT = 'FinancialDataEngineeringPlatform ' + [System.Net.NetworkCredential]::new('', $secEmail).Password.Trim()
} finally {
    $fredKey.Dispose()
    $secEmail.Dispose()
}
```

The check below prints neither value.

```powershell
@'
import os
from ingestion.sec import valid_user_agent
configured = os.getenv("FRED_API_KEY", "").strip() and valid_user_agent(os.getenv("SEC_USER_AGENT", ""))
raise SystemExit(0 if configured else 1)
'@ | python -
if ($LASTEXITCODE) { throw 'Configure the FRED key and SEC contact in this shell.' }

$archive = '.local/visitor-dashboard/source-2019-2025'
$bounds = @('--mode', 'backfill', '--start', '2019-01-01', '--end', '2025-12-31', '--data-dir', $archive)
python -m ingestion fred --fred-series DGS10 @bounds
if ($LASTEXITCODE) { throw 'FRED pilot failed. Check the local outcome before continuing.' }
python -m ingestion sec --sec-issuer MSFT @bounds
if ($LASTEXITCODE) { throw 'SEC pilot failed. Check the local outcome before continuing.' }

python -m ingestion fred --fred-series DGS2 --fred-series FEDFUNDS --fred-series CPIAUCSL --fred-series UNRATE --fred-series GDPC1 @bounds
if ($LASTEXITCODE) { throw 'Review the FRED outcome and retry only failed series.' }
python -m ingestion sec --sec-issuer AAPL --sec-issuer NVDA --sec-issuer AMZN --sec-issuer JPM --sec-issuer GS --sec-issuer BAC --sec-issuer JNJ --sec-issuer PFE --sec-issuer WMT --sec-issuer XOM --sec-issuer CVX @bounds
if ($LASTEXITCODE) { throw 'Review the SEC outcome and retry only failed issuers.' }

python -m scripts.build_history $archive .local/visitor-dashboard/history.duckdb --window 2019-01-01 2025-12-31
if ($LASTEXITCODE) { throw 'Local archive validation or dbt build failed.' }
python -m streamlit run dashboard/app.py --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false
```

The capture commands are for a new archive. After an interruption, use the local run records to identify missing or failed entities and rerun the same window for only those entities. Rebuild the database from the preserved archive with just `scripts.build_history`. The builder validates each committed manifest and its hashes, replays every batch in sequence, and uses the existing dbt project. It requires all configured entities and matching capture windows in full mode. Validation and dbt run on a temporary database. The published file changes only after a successful build.

After capture, close the credential shell or remove the two process variables with `Remove-Item Env:FRED_API_KEY, Env:SEC_USER_AGENT -ErrorAction SilentlyContinue`. Local rebuilding and dashboard verification use only the archived files.

Keep the original manifests, source bodies and normalized changes for reproducible results. Capturing the same observation range later can produce revised values. A FRED observation date says what time the value describes. The requested vintage date identifies the copy of FRED queried, and the UTC retrieval timestamp records when the response was saved. One capture of a seven-year range gives seven years of observations from one vintage. For SEC, the exact fiscal period, filing date and UTC archive capture each describe a different event.

The annual view uses a single SEC reporting definition and unit for each financial measure. It compares selected annual filings and annual-report balance-sheet values at fiscal year end, excluding overlapping periods and years with multiple eligible ends. Year labels follow the calendar year of the actual period end. Missing years remain blank, and exact unscaled values, filing dates, definitions and accession numbers are available in the tables. Economic lines break at explicit missing values and absent native periods.

## Rebuild the preserved real sample

For a known partial archive, use the original Phase 3B archive root in `$sampleArchive`. The archived deployment plan identifies that path locally.

```powershell
python -m scripts.build_history $sampleArchive .local/visitor-dashboard/archive-sample.duckdb --partial-replay --namespace fdep-demo
```

This run needs no source credentials. The archive provided two DGS10 batches and two Microsoft batches. It replayed 91 change rows and 136 SEC snapshot memberships, with all 31 dbt data tests passing. The result has 23 DGS10 dates from January 1–31, 2024, with 21 numeric values and two source-missing dates. The requested FRED vintage was November 20, 2026. The 25 Microsoft financial facts have March 31 or June 30, 2024 period ends, with filing dates from April 25 through July 30, 2024.

`python -m pytest --basetemp=.local/visitor-dashboard/pytest-final` reported 149 passes and one skip for the missing Airflow runtime. Chrome verification used the rebuilt real sample over localhost. It confirmed all three sections, the keyboard-operable economic date range, a $245.12 billion rounded Microsoft annual revenue display with an exact-value disclosure, and the four archived batches. In the narrow browser view the economic controls stacked and the page had no horizontal overflow.

## Completed 2019–2025 capture

The restored capture committed 6 FRED and 12 SEC batches. The local database contains 3,934 FRED observation rows and 8,395 SEC snapshot members (8,023 facts and 372 filings). dbt matched 3,700 eligible SEC candidates to filings and selected 3,682 company facts. All 43 nodes passed, including 31 data tests. The private dashboard was visually approved with the seven-year Treasury and Microsoft revenue charts.
