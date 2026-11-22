"""Build a disposable DuckDB RAW/OPS database from deterministic synthetic batches."""

import argparse
import json
import tomllib
from pathlib import Path
from typing import Any

import duckdb

from warehouse.numeric import NumericRangeError, checked_decimal


ROOT = Path(__file__).resolve().parents[1]
EXACT = "12345678901234567890123456.123456789012"
FRED_OBJECT = "raw/observations.json"
META_OBJECT = "raw/series.json"
FILING_OBJECT = "raw/submissions.json"
FACT_OBJECT = "raw/companyfacts.json"


def source_scope() -> dict:
    with (ROOT / "config/source_scope.toml").open("rb") as stream:
        return tomllib.load(stream)


def load_batch(
    db: duckdb.DuckDBPyConnection, source: str, entity: str, sequence: int,
    observed_at: str, rows: list[dict[str, Any]], *, committed: bool = True,
) -> None:
    batch_id = f"{source}-{entity}-{sequence}"
    paths = (FRED_OBJECT, META_OBJECT) if source == "fred" else (FILING_OBJECT, FACT_OBJECT)
    object_rows = [(f"{batch_id}-{i}", f"fixture/{path}", "fixture-hash", "{}")
                   for i, path in enumerate(paths)]
    db.executemany("insert into raw.source_object values (?, ?, ?, ?)", object_rows)
    db.executemany("insert into raw.batch_object values (?, ?, ?, ?, ?, ?)", [
        (batch_id, i, item[0], path, "{}", observed_at)
        for i, (path, item) in enumerate(zip(paths, object_rows, strict=True))
    ])
    table = "ingestion_record" if source == "fred" else "sec_snapshot_member"
    counts = dict(changes=0, members=0, requests=len(paths), quarantined=0)
    counts["changes" if source == "fred" else "members"] = len(rows)
    ordinals: dict[str, int] = {}
    for row in rows:
        dataset, value = row["dataset"], row.get("value")
        ordinal = ordinals.get(dataset, 0)
        ordinals[dataset] = ordinal + 1
        payload = json.dumps(row)
        try:
            number = checked_decimal(value)
        except NumericRangeError:
            number = None
            counts["quarantined"] += 1
            db.execute("insert into raw.numeric_quarantine values (?, ?, ?, ?, ?, ?)", [
                batch_id, "change" if source == "fred" else "snapshot",
                ordinal, value, "numeric_range", payload,
            ])
        db.execute(f"insert into raw.{table} values (?, ?, ?, ?, ?, ?, ?, ?)", [
            batch_id, dataset, ordinal, source, entity, payload, value,
            str(number) if number is not None else None,
        ])
    if committed:
        manifest = dict(
            source=source, entity=entity, run_id=batch_id, completed_at=observed_at,
            start="2022-01-01" if sequence == 1 else "2023-01-01", end="2024-01-01",
            manifest=f"metadata/batches/{source}/{entity}/{sequence:012}.json",
        )
        db.execute("insert into ops.batch_load values (?, ?, ?, ?, ?, ?, ?)", [
            batch_id, "manifest-hash", "receipt-hash", json.dumps(manifest),
            '{"identity":{"namespace":"fixture"}}', json.dumps(counts), observed_at,
        ])


def observation(series: str, snapshot: str, value: str | None, day: str = "2023-01-01") -> dict:
    return dict(
        dataset="observations", series_id=series, observation_date=day, snapshot_date=snapshot,
        realtime_start=snapshot, realtime_end=snapshot, is_missing=value is None, value=value,
        units="fixture units", frequency="fixture frequency", seasonal_adjustment="fixture adjustment",
        object_key=FRED_OBJECT, series_metadata_key=META_OBJECT, source_row=0,
    )


def filing(cik: str, accession: str, filed: str, form: str = "10-K", end: str = "2023-12-31") -> dict:
    return dict(
        dataset="filings", cik=cik, accession_number=accession, filing_date=filed,
        report_date=end, form=form, is_amendment=form.endswith("/A"),
        primary_document="report.htm", object_key=FILING_OBJECT, source_row=0,
        filing_metadata={"acceptanceDateTime": f"{filed}T20:00:00Z"},
    )


def fact(report: dict, tag: str, value: str, **overrides: Any) -> dict:
    return dict(
        dict(
            dataset="facts", cik=report["cik"], accession_number=report["accession_number"],
            filed_date=report["filing_date"], form=report["form"], is_amendment=report["is_amendment"],
            namespace="us-gaap", tag=tag, metric="revenue", unit="USD", normalized_unit="USD",
            period_class="annual", start_date="2023-01-01", end_date=report["report_date"],
            selection_eligible=True, value=value, fiscal_year=2023, fiscal_period="FY",
            object_key=FACT_OBJECT, source_row=0,
        ),
        **overrides,
    )


def populate(db: duckdb.DuckDBPyConnection) -> None:
    ddl = (ROOT / "warehouse/sql/001_raw.sql").read_text()
    ddl = ddl.replace("TIMESTAMP_TZ", "TIMESTAMPTZ").replace("NUMBER(", "DECIMAL(").replace(
        "LIKE RAW.INGESTION_RECORD", "AS SELECT * FROM RAW.INGESTION_RECORD WHERE FALSE",
    )
    db.execute(ddl)
    scope = source_scope()
    for series in scope["fred"]["series"]:
        load_batch(db, "fred", series, 1, "2024-02-01T08:00:00Z", [
            observation(series, "2024-02-01", EXACT),
        ])
    load_batch(db, "fred", "DGS10", 2, "2024-02-01T18:00:00Z", [
        observation("DGS10", "2024-02-01", "4.25"),
        observation("DGS10", "2024-02-01", None, "2023-01-02"),
        observation("DGS10", "2024-02-01", "0.0000000000001", "2023-01-03"),
    ])
    for cik in scope["sec"]["companies"].values():
        report = filing(cik, "0000000000-24-000001", "2024-01-20")
        load_batch(db, "sec", cik, 1, "2024-02-01T08:00:00Z", [
            report, fact(report, "Revenues", "100"), fact(report, "SalesRevenueNet", "91"),
            fact(report, "OperatingIncomeLoss", "17", metric="operating_income"),
        ])
    cik = scope["sec"]["companies"]["MSFT"]
    original = filing(cik, "0000000000-24-000001", "2024-01-20")
    amendment = filing(cik, "0000000000-24-000002", "2024-02-03", "10-K/A")
    quarter = filing(cik, "0000000000-24-000003", "2024-01-29", "10-Q")
    load_batch(db, "sec", cik, 2, "2024-02-05T08:00:00Z", [
        original, amendment, quarter,
        fact(original, "Revenues", "100"), fact(amendment, "Revenues", EXACT),
        fact(original, "SalesRevenueNet", "91"),
        fact(amendment, "SalesRevenueNet", "92"), fact(amendment, "SalesRevenueNet", "93"),
        fact(amendment, "Revenues", "110", start_date="2023-10-01", period_class="quarter"),
        fact(amendment, "Revenues", "130", normalized_unit="EUR"),
        fact(amendment, "Revenues", "222", end_date="2022-12-31"),
        fact(quarter, "NetIncomeLoss", "9", start_date="2023-07-01", period_class="year_to_date",
             metric="net_income"),
        fact(amendment, "ProfitLoss", "0.0000000000001", metric="net_income"),
        fact(amendment, "Assets", "150", start_date=None, period_class="instant", metric="assets"),
        fact(amendment, "Liabilities", "90", accession_number="unmatched", start_date=None,
             period_class="instant", metric="liabilities"),
    ])
    # A valid committed empty member set must supersede the prior full set.
    load_batch(db, "sec", scope["sec"]["companies"]["CVX"], 2, "2024-02-05T08:00:00Z", [])


def create_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Choose a new fixture path: {path}")
    with duckdb.connect(str(path)) as db:
        populate(db)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    create_fixture(parser.parse_args().database)

