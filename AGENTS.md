# Project instructions

- Keep Python ingestion, storage, loading, dbt, and Airflow responsibilities separate. Keep DAGs thin and expose ingestion through a callable interface shared by CLI and orchestration.
- Use type hints at module boundaries. Preserve source precision, request parameters safe for logging, and raw-object lineage. Log structured run identifiers, outcomes, durations, and row counts.
- Make retries safe, validate payloads before publication, and advance checkpoints only after successful batch publication. Account for revised observations and SEC amendments without losing source records.
- Run `python -m pytest` from the repository root. Ordinary tests must work offline and without credentials. Add regression coverage for paging, missing observations, malformed payloads, ambiguous financial facts, duplicate loads, and failed or retried batches as those features land.
- Keep secrets in environment variables or approved credential stores. Never commit real environment files, state files, keys, source downloads, or logs. Redact credential-bearing URLs and use scoped cloud roles.
- Update the relevant contract or architecture document when behavior changes. Record commands and observed results for integration claims. Keep the README short and distinguish implementation status from design.
- Require the user's explicit approval before creating cloud resources, upgrading accounts, incurring charges, or deploying to paid services. Present an account- and region-specific estimate first. Plan for $0–$10 and keep the planned total within $15 unless explicitly approved otherwise. Suspend and tear down demonstration resources and verify removal.
- Work within the current phase. Report verification and remaining gaps before advancing to a major phase. Keep project files in this repository and private backups outside Git working trees under the user's ChatGPT documents directory.
