# Financial Data Engineering Platform

Python captures FRED and SEC EDGAR data in validated, replayable batches. DuckDB and dbt Core produce traceable analytical views. Streamlit makes it easy to explore economic observations and compare company financials.

## Open the historical preview

From the repository root with Python 3.11 or 3.12, create a virtual environment.

```sh
python -m venv .venv
```

Activate it with `.venv\Scripts\Activate.ps1` in PowerShell or `source .venv/bin/activate` in Bash or zsh.

```sh
python -m pip install -r requirements-dashboard.txt
python -m streamlit run dashboard/app.py --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false
```

Open the localhost URL printed by Streamlit. A fresh checkout shows U.S. Treasury yields and Microsoft annual revenue from 2022–2024, with source dates and filing links. After installation the preview runs offline without credentials. A local publication takes precedence when available. [Preview provenance and reuse terms](docs/public-preview.md)

## Verification

- **Private local history.** The 2019–2025 capture produced 3,934 FRED observation rows and 3,682 selected company facts for 12 issuers. All 31 DuckDB dbt data tests passed.
- **Historical cloud demonstration.** Four batches committed through S3 to Snowflake RAW. Replay, rollback and teardown were verified. Snowflake dbt parity and the Linux Airflow runtime check remain pending.

[Architecture](docs/architecture.md) · [Build and test the pipeline offline](docs/phase5-airflow.md#run-the-local-smoke-test) · [Rebuild the private history](docs/dashboard-history.md) · [Release checklist](docs/phase7-publication.md)

[MIT code license](LICENSE) · [Separate preview data notices](preview/NOTICE.md)
