"""SEC submissions and Company Facts ingestion with candidate-level lineage."""

import re
from collections import defaultdict
from datetime import date
from typing import Any, Iterable

from ingestion.http import JsonClient, PayloadError, decode_json
from ingestion.models import Record, decimal_text, source_date
from storage.local import Batch, LocalStore, json_bytes


BASE = "https://data.sec.gov"
ACCESSION = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")
CONTACT = re.compile(r"[\x20-\x7e]*[A-Za-z0-9] +[^@\s]+@[^@\s]+\.[^@\s]+")
NAMESPACE = "us-gaap"
CONCEPTS = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "SalesRevenueNet": "revenue",
    "Revenues": "revenue",
    "OperatingIncomeLoss": "operating_income",
    "NetIncomeLoss": "net_income",
    "ProfitLoss": "net_income",
    "Assets": "assets",
    "Liabilities": "liabilities",
    "NetCashProvidedByUsedInOperatingActivities": "operating_cash_flow",
    "PaymentsToAcquirePropertyPlantAndEquipment": "capital_expenditures",
    "EarningsPerShareBasic": "eps_basic",
    "EarningsPerShareDiluted": "eps_diluted",
}


def valid_user_agent(value: str) -> bool:
    return CONTACT.fullmatch(value) is not None


def _check_cik(data: dict, cik: str) -> None:
    value = str(data.get("cik"))
    if not re.fullmatch(r"[0-9]{1,10}", value) or value.zfill(10) != cik:
        raise PayloadError("SEC response CIK does not match requested issuer")


def _filings(
    columns: Any, batch: Batch, forms: set[str], object_key: str,
) -> Iterable[Record]:
    required = ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")
    optional = {"acceptanceDateTime": str, "fileNumber": str, "isXBRL": int, "isInlineXBRL": int}
    if not isinstance(columns, dict) or not all(isinstance(columns.get(name), list) for name in required):
        raise PayloadError("SEC submissions are missing required filing columns")
    length = len(columns["accessionNumber"])
    present = [name for name in (*required, *optional) if name in columns]
    if any(not isinstance(columns[name], list) or len(columns[name]) != length for name in present):
        raise PayloadError("SEC submission column lengths do not match")
    for index in range(length):
        form = columns["form"][index]
        if not isinstance(form, str):
            raise PayloadError("Invalid SEC filing form")
        if form not in forms:
            continue
        filed = source_date(columns["filingDate"][index], "filing date")
        raw_report_date = columns["reportDate"][index]
        report_date = None if raw_report_date in (None, "") else source_date(raw_report_date, "filing report date")
        if (report_date or filed) < batch.start:
            continue
        accession = columns["accessionNumber"][index]
        document = columns["primaryDocument"][index]
        if (
            not isinstance(accession, str) or not ACCESSION.fullmatch(accession)
            or not isinstance(document, str) or not document or (report_date and filed < report_date)
        ):
            raise PayloadError("Invalid SEC accession, primary document, or filing date")
        metadata = {name: columns[name][index] for name in optional if name in columns}
        if any(value is not None and not isinstance(value, optional[name]) for name, value in metadata.items()):
            raise PayloadError("Unexpected SEC optional filing metadata type")
        yield Record("filings", (accession,), {
            "cik": batch.entity, "accession_number": accession, "filing_date": filed.isoformat(),
            "report_date": report_date.isoformat() if report_date else None,
            "form": form, "primary_document": document,
            "is_amendment": form.endswith("/A"),
            "filing_metadata": metadata,
        }, {"object_key": object_key, "source_row": index})


def _submissions(client: JsonClient, batch: Batch, headers: dict, forms: set[str]) -> list[Record]:
    name = f"CIK{batch.entity}.json"
    response = client.get(f"{BASE}/submissions/{name}", headers=headers)
    key = batch.archive("submissions", response, {"file": name})
    _check_cik(response.data, batch.entity)
    filings = response.data.get("filings")
    if not isinstance(filings, dict) or not isinstance(filings.get("files"), list):
        raise PayloadError("SEC submissions are missing filing history")
    records = list(_filings(filings.get("recent"), batch, forms, key))
    visited = set()
    for entry in filings["files"]:
        if not isinstance(entry, dict):
            raise PayloadError("Invalid SEC historical submissions descriptor")
        through = source_date(entry.get("filingTo"), "archive filingTo")
        if through < batch.start:
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not re.fullmatch(rf"CIK{batch.entity}-submissions-[0-9]+\.json", name):
            raise PayloadError("Invalid SEC historical submissions filename")
        if name in visited:
            raise PayloadError("Duplicate SEC historical submissions filename")
        visited.add(name)
        archive = client.get(f"{BASE}/submissions/{name}", headers=headers)
        key = batch.archive("submissions_history", archive, {"file": name})
        records.extend(_filings(archive.data, batch, forms, key))
    return records


def period_class(start: date | None, end: date, form: str) -> str:
    if start is None:
        return "instant"
    days = (end - start).days + 1
    if days < 1:
        raise PayloadError("SEC fact start follows its end")
    if 350 <= days <= 380 and form.startswith("10-K"):
        return "annual"
    if 70 <= days <= 110:
        return "quarter"
    if form.startswith("10-Q") and (150 <= days <= 215 or 235 <= days <= 305):
        return "year_to_date"
    return "other_duration"


def _facts(data: dict, batch: Batch, object_key: str, filings: dict, forms: set[str]) -> Iterable[Record]:
    namespaces = data.get("facts")
    if not isinstance(namespaces, dict):
        raise PayloadError("SEC Company Facts is missing taxonomy data")
    taxonomy = namespaces.get(NAMESPACE, {})
    if not isinstance(taxonomy, dict):
        raise PayloadError("SEC Company Facts has an invalid US-GAAP taxonomy")
    batch.metadata["missing_mapped_metrics"] = sorted(
        set(CONCEPTS.values()) - {metric for tag, metric in CONCEPTS.items() if tag in taxonomy}
    )
    for tag, metric in CONCEPTS.items():
        if tag not in taxonomy:
            continue
        concept = taxonomy[tag]
        units = concept.get("units") if isinstance(concept, dict) else None
        if not isinstance(units, dict):
            raise PayloadError("SEC fact concept is missing units")
        for unit, items in units.items():
            if not isinstance(items, list):
                raise PayloadError("SEC facts for a unit must be a list")
            for index, item in enumerate(items):
                if not isinstance(item, dict) or not isinstance(item.get("form"), str):
                    raise PayloadError("Invalid SEC financial fact")
                form = item["form"]
                if form not in forms:
                    continue
                end = source_date(item.get("end"), "fact end")
                if not batch.start <= end <= batch.end:
                    continue
                yield _fact_record(item, index, unit, tag, metric, end, batch, object_key, filings)


def _fact_record(
    item: dict, index: int, unit: str, tag: str, metric: str, end: date,
    batch: Batch, object_key: str, filings: dict,
) -> Record:
    accession = item.get("accn")
    if not isinstance(accession, str) or not ACCESSION.fullmatch(accession):
        raise PayloadError("SEC financial fact is missing a valid accession")
    filed = source_date(item.get("filed"), "fact filed date")
    if filed < end:
        raise PayloadError("SEC fact filed date precedes period end")
    start = source_date(item["start"], "fact start") if item.get("start") is not None else None
    start_text = start.isoformat() if start else None
    end_text = end.isoformat()
    form = item["form"]
    fiscal_year, fiscal_period, frame = item.get("fy"), item.get("fp"), item.get("frame")
    if (
        (fiscal_year is not None and type(fiscal_year) is not int)
        or (fiscal_period is not None and not isinstance(fiscal_period, str))
        or (frame is not None and not isinstance(frame, str))
    ):
        raise PayloadError("Unexpected SEC fiscal metadata type")
    period = period_class(start, end, form)
    value = decimal_text(item.get("val"))
    filing = filings.get(accession)
    normalized_unit = "USD/shares" if unit in {"USD/shares", "USD-per-shares"} else unit
    expected_unit = "USD/shares" if metric.startswith("eps_") else "USD"
    expected_instant = metric in {"assets", "liabilities"}
    matched = bool(filing and filing["form"] == form and filing["filing_date"] == filed.isoformat())
    eligible = (
        matched and normalized_unit == expected_unit and (start is None) == expected_instant
        and period != "other_duration"
    )
    key = (accession, NAMESPACE, tag, unit, start_text, end_text)
    return Record("facts", key, {
        "cik": batch.entity, "accession_number": accession, "namespace": NAMESPACE,
        "tag": tag, "metric": metric, "unit": unit, "normalized_unit": normalized_unit,
        "start_date": start_text, "end_date": end_text, "value": value, "form": form,
        "filed_date": filed.isoformat(), "fiscal_year": fiscal_year, "fiscal_period": fiscal_period,
        "period_class": period, "is_amendment": form.endswith("/A"),
    }, {
        "object_key": object_key, "source_row": index, "frame": frame,
        "filing_matched": matched, "filing_report_date": filing["report_date"] if matched else None,
        "selection_eligible": eligible,
    }, (NAMESPACE, tag, unit, start_text, end_text))


def _normalize(
    batch: Batch, submissions: list[Record], data: dict, object_key: str, forms: set[str],
) -> list[Record]:
    filings = {}
    for record in submissions:
        accession = record.key[0]
        if accession in filings and filings[accession] != record.fields:
            raise PayloadError("Conflicting submissions metadata for one accession")
        filings[accession] = record.fields
    _check_cik(data, batch.entity)
    facts = list(_facts(data, batch, object_key, filings, forms))
    conflicts = defaultdict(set)
    for record in facts:
        conflicts[record.key].add(record.fields["value"])
    batch.metadata.update(
        conflicting_fact_keys=sum(len(values) > 1 for values in conflicts.values()),
        unmatched_fact_rows=sum(not record.lineage["filing_matched"] for record in facts),
    )
    matched_accessions = {record.key[0] for record in facts}
    return [
        record for record in submissions
        if (record.fields["report_date"] or record.fields["filing_date"]) <= batch.end.isoformat()
        or record.key[0] in matched_accessions
    ] + facts


def fetch(client: JsonClient, batch: Batch, *, user_agent: str, forms: set[str]) -> list[Record]:
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    submissions = _submissions(client, batch, headers, forms)
    name = f"CIK{batch.entity}.json"
    response = client.get(f"{BASE}/api/xbrl/companyfacts/{name}", headers=headers)
    key = batch.archive("companyfacts", response, {"file": name})
    batch.metadata["forms"] = sorted(forms)
    return _normalize(batch, submissions, response.data, key, forms)


def read_snapshot(store: LocalStore, manifest: dict) -> list[dict]:
    """Replay one committed SEC snapshot, including unchanged rows, from its raw objects."""
    if manifest["source"] != "sec" or manifest["status"] != "success":
        raise ValueError("Expected a successful SEC manifest")
    store.validate_batch(manifest)
    batch = Batch(
        store, "sec", manifest["entity"], manifest["run_id"],
        date.fromisoformat(manifest["start"]), date.fromisoformat(manifest["end"]),
    )
    forms = set(manifest["metadata"]["forms"])
    filings = []
    facts = []
    for reference in manifest["objects"]:
        endpoint, key = reference["endpoint"], reference["object_key"]
        data = decode_json(store.read_object(reference)).data
        if endpoint == "submissions":
            _check_cik(data, batch.entity)
            filings.extend(_filings(data["filings"]["recent"], batch, forms, key))
        elif endpoint == "submissions_history":
            filings.extend(_filings(data, batch, forms, key))
        elif endpoint == "companyfacts":
            facts.append((data, key))
    if len(facts) != 1:
        raise PayloadError("SEC manifest must reference one Company Facts response")
    (data, key), = facts
    unique = {}
    for record in _normalize(batch, filings, data, key, forms):
        identity = (record.dataset, record.key, json_bytes(record.fields))
        unique.setdefault(identity, {
            **record.fields, **record.lineage, "dataset": record.dataset, "source": "sec",
            "ingestion_timestamp": manifest["completed_at"],
        })
    return list(unique.values())


def select_period_candidates(
    facts: Iterable[dict], filings: Iterable[dict], *, filed_through: date,
    original: bool = False, observed_through: str | None = None,
    snapshot_rows: Iterable[dict] | None = None,
) -> list[dict]:
    """Rank supplied history, or restrict both candidates and filings to a snapshot."""
    if snapshot_rows is not None:
        snapshot = list(snapshot_rows)
        facts = [row for row in snapshot if row["dataset"] == "facts"]
        filings = [row for row in snapshot if row["dataset"] == "filings"]
    filing_versions = defaultdict(list)
    for filing in filings:
        if observed_through is None or filing["ingestion_timestamp"] <= observed_through:
            filing_versions[(filing["cik"], filing["accession_number"])].append(filing)
    groups = defaultdict(list)
    for fact in facts:
        if observed_through is not None and fact["ingestion_timestamp"] > observed_through:
            continue
        if fact["filed_date"] > filed_through.isoformat():
            continue
        versions = filing_versions[(fact["cik"], fact["accession_number"])]
        if not versions:
            continue
        filing = max(versions, key=lambda row: row["ingestion_timestamp"])
        if not _comparable(fact, filing, original):
            continue
        key = tuple(fact[name] for name in (
            "cik", "metric", "period_class", "start_date", "end_date", "normalized_unit",
        ))
        groups[key].append(fact)
    results = []
    for key, candidates in groups.items():
        rank = min if original else max
        winning_date = rank(row["filed_date"] for row in candidates)
        contenders = [row for row in candidates if row["filed_date"] == winning_date]
        values = {row["value"] for row in contenders}
        results.append({
            "key": key, "filed_date": winning_date, "ambiguous": len(values) > 1,
            "value": values.pop() if len(values) == 1 else None, "candidates": contenders,
        })
    return results


def select_snapshot_candidates(
    store: LocalStore, entity: str, *, filed_through: date,
    original: bool = False, observed_through: str | None = None,
    manifest: dict | None = None,
) -> dict:
    """Select only members of one validated SEC snapshot and return its scope."""
    from storage.manifest import IntegrityError, timestamp

    batches = store.manifests("sec", entity)
    if observed_through is not None:
        cutoff = timestamp(observed_through)
        batches = [batch for batch in batches if timestamp(batch["completed_at"]) <= cutoff]
    if manifest is not None:
        batches = [batch for batch in batches if batch == manifest]
        if not batches:
            raise IntegrityError("Requested SEC snapshot is not committed or exceeds the observation cutoff")
    if not batches:
        return {"manifest": None, "start": None, "end": None, "candidates": []}
    selected = batches[-1]
    rows = read_snapshot(store, selected)
    return {
        "manifest": selected["manifest"], "start": selected["start"], "end": selected["end"],
        "candidates": select_period_candidates(
            [], [], filed_through=filed_through, original=original, snapshot_rows=rows,
        ),
    }


def _comparable(fact: dict, filing: dict, original: bool) -> bool:
    if filing["form"] != fact["form"] or filing["filing_date"] != fact["filed_date"]:
        return False
    metric = fact["metric"]
    expected_unit = "USD/shares" if metric.startswith("eps_") else "USD"
    expected_instant = metric in {"assets", "liabilities"}
    if (
        fact["normalized_unit"] != expected_unit or fact["period_class"] == "other_duration"
        or (fact["start_date"] is None) != expected_instant
    ):
        return False
    return not original or (not fact["is_amendment"] and fact["end_date"] == filing["report_date"])
