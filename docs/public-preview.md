# Public historical preview

From a clean checkout, install `requirements-dashboard.txt` and start Streamlit as shown in the [README](../README.md). The app reads the two versioned CSV extracts directly. A local analytical publication or an explicit `FDEP_DUCKDB_PATH` takes precedence. The offline preview needs no API calls, credentials, DuckDB file, or dbt build.

| Extract | Exact scope |
| --- | --- |
| `treasury-10y.csv` | 749 published 10-year par yield observations, in percent, from January 3, 2022 through December 31, 2024. Counts by year are 249, 250 and 250. The source has no missing values in this column for the selected rows. Weekends and other days absent from Treasury's table remain gaps. |
| `microsoft-revenue.csv` | Three consolidated Microsoft fiscal years ending June 30, 2022, 2023 and 2024. Exact source amounts are 198,270,000,000 USD, 211,915,000,000 USD and 245,122,000,000 USD. The chart scales to billions. The file retains dates, form, accession, CIK, taxonomy, tag, unit and filing URL. |

The domestic Treasury preview measures use the directly published Treasury series. FRED's DGS10 page identifies the Board of Governors as its source and asks for citation of both the source and FRED when used through FRED. FRED also applies its own service and redistribution terms. This preview uses the Treasury archive under the license listed in the federal catalog and includes no FRED rows or charts. Treasury computes the published series at fixed maturity. The preview does not estimate values on absent dates. [FRED DGS10 citation](https://fred.stlouisfed.org/series/DGS10) · [FRED terms](https://fred.stlouisfed.org/legal/terms/) · [Treasury dataset and CC0 listing](https://catalog.data.gov/dataset/interest-rate-statistics-daily-treasury-yield-curve-rates)

The Microsoft values are factual extracts from public EDGAR filing content, which the SEC permits others to reuse. Each amount was checked against the original annual filing for that year. All three use US GAAP `RevenueFromContractWithCustomerExcludingAssessedTax` in USD for complete, nonoverlapping twelve-month periods. [SEC reuse policy](https://www.sec.gov/about/webmaster-frequently-asked-questions) · [2022 Form 10-K](https://www.sec.gov/Archives/edgar/data/789019/000156459022026876/msft-10k_20220630.htm) · [2023 Form 10-K](https://www.sec.gov/Archives/edgar/data/789019/000095017023035122/msft-20230630.htm) · [2024 Form 10-K](https://www.sec.gov/Archives/edgar/data/789019/000095017024087843/msft-20240630.htm)

The full FRED/SEC archive, manifest and warehouse history stay private. The two reviewed extracts include only the fields above and contain no source payloads, run identifiers, credentials, private contacts or cloud resource identifiers. See the [data notices](../preview/NOTICE.md) for the separate source terms. The synthetic fixtures remain available for pipeline tests.

## Regenerate and compare

1. Download the [Treasury 1990–2024 CSV](https://home.treasury.gov/system/files/276/yield-curve-rates-1990-2024.csv) into an ignored folder. The reviewed file has SHA-256 `258a594eb64e9d21d9e8574b0b8580b0a5230dce56bb284ec6aa49a9a260897f`.
2. Run the export below with the validated private historical publication. The Treasury export keeps calendar years 2022–2024 and the source's `10 Yr` column. The SEC export selects the three published Microsoft annual revenue facts. Without the private archive, the SEC extract can also be checked against the linked 10-Ks by using each year's reported revenue in millions and restoring the whole-dollar unit.
3. Compare the output SHA-256 digests before replacing any release files. Review the source, date scope, and terms again before broadening the preview.

```powershell
python -m scripts.prepare_public_preview .local/release-preview/treasury-source.csv .local/visitor-dashboard/history.duckdb .local/release-preview/regenerated
Get-FileHash .local/release-preview/regenerated/*.csv
```

| File | SHA-256 (UTF-8, LF) |
| --- | --- |
| `treasury-10y.csv` | `987251337208cb1e241a5b3a5f680e1a06be2bf95071a9bc8acea1c80068835f` |
| `microsoft-revenue.csv` | `4a6577fe146e11b2fa84504710dcaabd51d2be91469660fef44e9b1cfdab5ce1` |
