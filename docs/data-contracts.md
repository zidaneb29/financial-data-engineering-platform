# Source scope and data contracts

The initial universe lives in [source_scope.toml](../config/source_scope.toml). Start with six FRED series and 12 U.S. issuers. Bound the first demonstration to a short date range and a subset of the configured universe before running the full backfill locally.

The [validated batch contract](cloud-loader-contract.md) governs local manifest schemas, integrity validation and the proposed warehouse-loader interface. SEC available-candidate queries must use explicit snapshot membership. Cumulative changes alone represent historical candidates.

## FRED

Backfill observations from 2015-01-01. Keep native frequency and request levels (`units=lin`). Fetch series metadata independently and preserve title, units, frequency, seasonal adjustment, source attribution, and update metadata where available.

| Series | Meaning | Cadence |
| --- | --- | --- |
| FEDFUNDS | Effective federal funds rate | Monthly |
| CPIAUCSL | Seasonally adjusted CPI for all urban consumers | Monthly |
| UNRATE | Unemployment rate | Monthly |
| GDPC1 | Real gross domestic product | Quarterly |
| DGS2 | Two-year Treasury constant maturity rate | Daily |
| DGS10 | Ten-year Treasury constant maturity rate | Daily |

Use the v1 `series` and `series/observations` endpoints. Request JSON and page observations by `limit` and `offset` in ascending date order. Fix the observation bounds and same-day `realtime_start` and `realtime_end` to a selected snapshot date across pages. Check the returned count, offsets and unique dates. Treat an empty first page with a reported count of zero as valid. Treat an unexpected empty intermediate page as incomplete. Rerunning a past observation range with a current snapshot date yields the revised history available on that date. [Observations endpoint](https://fred.stlouisfed.org/docs/api/fred/series_observations.html) · [Real-time periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html)

After initial coverage, refresh a configurable overlap of 730 days by default and use backfills to reconcile older revisions. Preserve the requested snapshot date and returned real-time bounds. The snapshot date records the retrieval view of the data. Historical point-in-time research would require explicit vintage retrieval and validation. Represent `.` as null with an explicit missing flag. Use exact decimal parsing and serialize decimal text in local JSON Lines. Keep source dates separate from ingestion timestamps. Treasury comparisons use overlapping available days or a documented monthly aggregation. Compute CPI year-over-year from comparable months 12 months apart.

Sign in to a FRED account, request an application API key, and set `FRED_API_KEY` locally. Users should use their own keys. Redact the query string from logs and exception telemetry. Start with one request per second as a project setting, retry boundedly on rate limits and transient failures, and surface invalid credentials. Review FRED terms and series attribution before redistributing datasets or report exports. [API keys](https://fred.stlouisfed.org/docs/api/api_key.html) · [v1 errors](https://fred.stlouisfed.org/docs/api/fred/errors.html) · [FRED terms](https://fred.stlouisfed.org/docs/api/terms_of_use.html)

## SEC EDGAR

Use public read endpoints `data.sec.gov/submissions/CIK##########.json` and `data.sec.gov/api/xbrl/companyfacts/CIK##########.json`. Preserve the zero-padded CIK as text. Submissions provides company and filing metadata and may reference older submission JSON files. Follow those references when needed to resolve filings in scope. Company Facts returns company-level standardized taxonomy facts grouped by concept and unit. Issuer extensions, segment dimensionality, and some line items may require filing-level XBRL in future work. [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

The public read API requires no key. Set `SEC_USER_AGENT` to a project or organization name followed by a monitored email address. The SEC publishes an aggregate maximum of 10 requests per second. Start at two per second for the entire project, use bounded retries on transient failures and 429, and stop and diagnose 403 or repeated blocks. Poll once per day, cache complete responses, and reuse unchanged bodies. Refresh Company Facts even when the submissions list appears unchanged to accommodate publication lag or data corrections. [SEC fair access](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) · [SEC security policy](https://www.sec.gov/files/privacy.htm)

Use fiscal period end from 2019-01-01 and forms 10-K, 10-Q and their amendments. Preserve all returned facts in raw snapshots. Normalized candidates use the `us-gaap` namespace. They retain source units and mark unit compatibility for selection. Company Facts excludes custom taxonomies and facts outside company-wide context. Mapping issuer-specific tags requires filing-level XBRL and validation of the context and metric. Candidate mappings require review against real filings before promotion.

| Metric | Example concepts | Unit and period |
| --- | --- | --- |
| Revenue | RevenueFromContractWithCustomerExcludingAssessedTax, SalesRevenueNet, Revenues | USD duration; review financial sector definitions separately |
| Operating income | OperatingIncomeLoss | USD duration |
| Net income | NetIncomeLoss, ProfitLoss | USD duration; check reporting entity scope |
| Assets | Assets | USD instant |
| Liabilities | Liabilities | USD instant |
| Operating cash flow | NetCashProvidedByUsedInOperatingActivities | USD duration |
| Capital expenditures | PaymentsToAcquirePropertyPlantAndEquipment | USD duration; preserve reported sign |
| Basic and diluted EPS | EarningsPerShareBasic, EarningsPerShareDiluted | USD/shares duration; separate metrics |

Join facts to filings on CIK and accession. Use fact start/end dates and filing metadata to classify instant, annual, standalone quarter, and year-to-date facts. Preserve fiscal-year and fiscal-period labels as source metadata. A quarterly filing can contain year-to-date and prior-period facts. Initial analytics exclude ambiguous durations, Q4 derivations, incompatible tags and units, and unverified bank/non-bank revenue comparisons. Use comparable fiscal periods for growth and identical periods for margin numerators and denominators. Preserve exact values before analytical rounding.

Phase 1 preserves the original accession and amendments as distinct records. Form suffix marks an amendment. A subsequent filing with a changed comparative value can indicate a restatement candidate. Confirmation requires supporting filing evidence. The [local ingestion guide](local-ingestion.md) describes candidate ranking, snapshot replay, and historical availability limits.

## Warehouse model

The implemented Phase 4 grains, eligibility rules and cutoffs are defined in [Phase 4 dbt transformations](phase4-dbt.md#time-grain-and-provenance). The following table records the original downstream design. The Phase 2B RAW landing tables and actual grains are documented in [cloud integration](cloud-integration.md#raw-schema). Local JSON Lines schemas are described in [local ingestion](local-ingestion.md). RAW stores original JSON and normalized rows as text to preserve numeric values beyond warehouse conversion limits. A checked NUMBER(38,12) projection is provisional, and unsupported projections are quarantined with their source text. Later staging can use DATE, UTC timestamps, and exact profiled numeric types.

| Object | Grain and key | Important fields |
| --- | --- | --- |
| RAW.SOURCE_OBJECT | One archived object, key `object_key` | source, entity, endpoint, SHA-256, payload |
| RAW.BATCH_OBJECT | One request result/page per batch, key `batch_id, request_id` | object key, retrieval time, sanitized parameters, status |
| STAGING.FRED_OBSERVATION | One observation change per series, observation date and committed batch | snapshot date, decimal value, missing flag, real-time bounds, object lineage |
| STAGING.SEC_FILING | One filing per CIK and accession | form, filed date, acceptance timestamp where available, reporting date, primary document, amendment flag |
| STAGING.SEC_FACT | One distinct as-filed candidate per CIK, accession, taxonomy, tag, unit, start, end, and exact value | nullable start for instants, source fiscal labels, frame, object lineage |
| ANALYTICS.DIM_DATE | One calendar date, key `date` | calendar attributes; issuer fiscal periods stay on facts |
| ANALYTICS.DIM_COMPANY | One issuer per CIK | display name, ticker, industry |
| ANALYTICS.DIM_ECONOMIC_INDICATOR | One row per series ID | latest source metadata and cadence |
| ANALYTICS.FACT_ECONOMIC_OBSERVATIONS | One latest row per series and observation date | value, missing flag, selected snapshot date |
| ANALYTICS.FACT_COMPANY_FINANCIALS | One comparable selection per CIK, metric, period class, normalized start, end and unit | value, selected accession, filed date, tag, lineage |
| OPS.BATCH_LOAD | One committed warehouse load per batch | manifest hash, timestamps, inserted/rejected counts |
| OPS.PIPELINE_RUN | One execution attempt per run, stage, entity and attempt number | outcome, durations, counts, sanitized error code |

Treat a missing start as a distinct instant in natural-key comparisons with null-safe equality. Deduplicate identical SEC facts, retain conflicting candidates, and retain the relationship to archived responses through raw batch membership. For FRED, retain a batch or version discriminator in the history layer when multiple values were fetched on the same snapshot date. Use the requested snapshot date and committed retrieval order for latest selection, and expose same-day changes for reconciliation. Build a filing-history intermediate model so the company mart can apply documented version selection without losing prior accessions.

## Deferred market data

Leave market prices outside the initial warehouse. In the analytics phase, evaluate candidates against permitted redistribution, splits and dividends treatment, coverage, rate limits, completeness, and total cost before selecting a provider. Keep the initial dashboard independent of market prices.

