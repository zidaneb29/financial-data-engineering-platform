"""Read the credential-free static extracts without loading a private archive."""

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from dashboard.queries import Row


PREVIEW = Path(__file__).resolve().parents[1] / "preview"
TREASURY_SOURCE = "https://home.treasury.gov/interest-rates-data-csv-archive/"


def treasury_observations() -> list[Row]:
    with (PREVIEW / "treasury-10y.csv").open(encoding="utf-8", newline="") as stream:
        records = list(csv.DictReader(stream))
    for row in records:
        row["observation_date"] = date.fromisoformat(row["observation_date"])
        value = row["value_text"]
        row["value_number"] = None if value in {"", "N/A"} else Decimal(value)
    return records


def microsoft_revenue() -> list[Row]:
    with (PREVIEW / "microsoft-revenue.csv").open(encoding="utf-8", newline="") as stream:
        records = list(csv.DictReader(stream))
    for row in records:
        for field in ("period_start", "period_end", "filed_date"):
            row[field] = date.fromisoformat(row[field])
        row.update(value_number=Decimal(row["value_text"]), publication="Published", period_class="annual")
    return records
