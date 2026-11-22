"""Prepare the reviewed public preview from Treasury CSV and local SEC analytics."""

import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from dashboard.queries import Row, open_analytics, rows


FIRST_YEAR = 2022
LAST_YEAR = 2024


def treasury_records(source: Path) -> list[Row]:
    records = []
    with source.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            day = datetime.strptime(row["Date"], "%m/%d/%y").date()
            if FIRST_YEAR <= day.year <= LAST_YEAR:
                value = row["10 Yr"]
                if value not in {"", "N/A"} and not Decimal(value).is_finite():
                    raise ValueError("Treasury preview contains an invalid rate")
                records.append({"observation_date": day, "value_text": value, "units": "Percent"})
    records.sort(key=lambda row: row["observation_date"])
    days = {row["observation_date"] for row in records}
    if len(days) != len(records) or {day.year for day in days} != {2022, 2023, 2024}:
        raise ValueError("Expected unique Treasury dates covering all three preview years")
    return records


def microsoft_records(database: Path) -> list[Row]:
    with open_analytics(database) as db:
        records = rows(db, """
            select cik, period_start, period_end, filed_date, form, taxonomy, tag,
                   source_unit, value_text, accession_number, primary_document
            from fdep_analytics.fact_company_financials
            where ticker = 'MSFT' and metric = 'revenue' and period_class = 'annual'
              and taxonomy = 'us-gaap' and tag = 'RevenueFromContractWithCustomerExcludingAssessedTax'
              and form = '10-K' and source_unit = 'USD'
              and period_end between ? and ?
            order by period_end
        """, (date(FIRST_YEAR, 1, 1), date(LAST_YEAR, 12, 31)))
    if [row["period_end"] for row in records] != [date(year, 6, 30) for year in range(FIRST_YEAR, LAST_YEAR + 1)]:
        raise ValueError("Expected three comparable Microsoft filing years")
    for row in records:
        cik = int(row["cik"])
        accession = row["accession_number"].replace("-", "")
        document = row.pop("primary_document")
        row["filing_url"] = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("treasury_csv", type=Path)
    parser.add_argument("historical_database", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sources = {
        "treasury-10y.csv": treasury_records(args.treasury_csv),
        "microsoft-revenue.csv": microsoft_records(args.historical_database),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    for name, records in sources.items():
        with (args.output / name).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(records)
        print(f"{name}: {len(records)} rows")


if __name__ == "__main__":
    main()
