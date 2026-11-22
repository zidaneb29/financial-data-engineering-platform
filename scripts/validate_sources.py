"""Controlled source-only validation with sanitized evidence and no cloud calls."""

import argparse
import os
import tomllib
from collections import Counter
from datetime import date
from decimal import Decimal
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import requests

from ingestion import fred, sec
from ingestion.http import JsonClient, decode_json
from ingestion.models import decimal_text, utc_now
from ingestion.pipeline import IngestionTask, run_ingestion
from storage.local import LocalStore, atomic_write, json_bytes
from storage.manifest import digest, require
from storage.transfer import S3Transfer, prepare_batch
from warehouse.loader import SnowflakeLoader
from warehouse.numeric import NumericRangeError, checked_decimal


ROOT = Path(__file__).resolve().parents[1]


def numeric_profile(rows: list[dict]) -> dict:
    values = [row["value"] for row in rows if row.get("value") is not None]
    max_integer = max_scale = unsupported = 0
    for value in values:
        number = Decimal(value)
        _sign, digits, exponent = number.as_tuple()
        if not number.is_zero():
            while digits[-1] == 0:
                digits, exponent = digits[:-1], exponent + 1
            max_integer = max(max_integer, max(0, len(digits) + exponent))
            max_scale = max(max_scale, max(0, -exponent))
        try:
            checked_decimal(value)
        except NumericRangeError:
            unsupported += 1
    return {
        "numeric_rows": len(values), "max_integer_digits": max_integer,
        "max_fractional_digits": max_scale, "unsupported_number_38_12": unsupported,
        "null_values": sum("value" in row and row["value"] is None for row in rows),
    }


def compare_source_rows(store: LocalStore, rows: list[dict]) -> int:
    """Compare every normalized record to its original indexed source record."""
    cached = {}
    for row in rows:
        key = row["object_key"]
        if key not in cached:
            cached[key] = decode_json((store.root / key).read_bytes()).data
        raw = cached[key]
        index = row["source_row"]
        if row["source"] == "fred":
            item = raw["observations"][index]
            value = None if item["value"] == "." else decimal_text(item["value"], from_text=True)
            require(row["observation_date"] == item["date"] and row["value"] == value,
                    "FRED source comparison failed")
            metadata = decode_json((store.root / row["series_metadata_key"]).read_bytes()).data["seriess"][0]
            require(row["series_id"] == metadata["id"] and row["units"] == metadata["units"]
                    and row["frequency"] == metadata["frequency"].lower(),
                    "FRED metadata comparison failed")
        elif row["dataset"] == "facts":
            item = raw["facts"][row["namespace"]][row["tag"]]["units"][row["unit"]][index]
            expected = {
                "accession_number": item["accn"], "start_date": item.get("start"), "end_date": item["end"],
                "form": item["form"], "filed_date": item["filed"],
                "fiscal_year": item.get("fy"), "fiscal_period": item.get("fp"),
                "value": decimal_text(item["val"]),
            }
            require(all(row[name] == value for name, value in expected.items()), "SEC fact source comparison failed")
        else:
            columns = raw["filings"]["recent"] if "filings" in raw else raw
            require(
                row["accession_number"] == columns["accessionNumber"][index]
                and row["filing_date"] == columns["filingDate"][index]
                and row["report_date"] == (columns["reportDate"][index] or None)
                and row["form"] == columns["form"][index]
                and row["primary_document"] == columns["primaryDocument"][index],
                "SEC filing source comparison failed",
            )
    return len(rows)


def inspect_batch(store: LocalStore, manifest: dict) -> dict:
    prepared = prepare_batch(store, manifest, "source-validation")
    rows = sec.read_snapshot(store, manifest) if manifest["source"] == "sec" else prepared.rows
    compared = compare_source_rows(store, rows)
    # Exercise the actual loader's input preparation without entering load(),
    # which would verify S3 and create a connection.
    def forbidden_connection():
        raise AssertionError("Source validation must not connect to a warehouse")

    transfer = S3Transfer(store, None, bucket="offline-validation-only", namespace="source-validation")
    loader = SnowflakeLoader(store, transfer, forbidden_connection, target_id="offline-input-check")
    changes, members, quarantine = loader._records(prepared)
    report = {
        "manifest": manifest["manifest"], "schema_version": manifest["schema_version"],
        "batch_id": prepared.batch_id, "manifest_sha256": manifest["manifest_sha256"],
        "source_rows_compared": compared, "numeric_profile": numeric_profile(rows),
        "loader_input": {"changes": len(changes), "snapshot_members": len(members), "quarantined": len(quarantine)},
        "counts": manifest["counts"], "datasets": dict(Counter(row["dataset"] for row in rows)),
    }
    if manifest["source"] == "sec":
        facts = [row for row in rows if row["dataset"] == "facts"]
        source_reference = next(item for item in manifest["objects"] if item["endpoint"] == "companyfacts")
        available_namespaces = sorted(decode_json(store.read_object(source_reference)).data["facts"])
        selected = sec.select_snapshot_candidates(store, manifest["entity"], filed_through=date.today(), manifest=manifest)
        historical = sec.select_snapshot_candidates(
            store, manifest["entity"], filed_through=date.today(), observed_through=manifest["completed_at"],
        )
        original = sec.select_snapshot_candidates(
            store, manifest["entity"], filed_through=date.today(), manifest=manifest, original=True,
        )
        report["sec"] = {
            "tags": sorted({row["tag"] for row in facts}), "units": sorted({row["unit"] for row in facts}),
            "namespaces": sorted({row["namespace"] for row in facts}),
            "available_source_namespaces": available_namespaces,
            "period_classes": dict(Counter(row["period_class"] for row in facts)),
            "fiscal_periods": dict(Counter(str(row["fiscal_period"]) for row in facts)),
            "amended_facts": sum(row["is_amendment"] for row in facts),
            "amended_filings": sum(row["is_amendment"] for row in rows if row["dataset"] == "filings"),
            "ambiguous_selections": sum(row["ambiguous"] for row in selected["candidates"]),
            "original_candidate_groups": len(original["candidates"]),
            "historical_snapshot_matches": historical["manifest"] == manifest["manifest"],
            "diagnostics": manifest["metadata"],
        }
    return report


def run_validation(output: Path, source: str = "all") -> dict:
    output = output.resolve()
    require(output.is_relative_to((ROOT / ".local").resolve()), "Validation output must be under the repository .local directory")
    output.mkdir(parents=True, exist_ok=False)
    store = LocalStore(output / "archive")
    scope = tomllib.loads((ROOT / "config/source_scope.toml").read_text(encoding="utf-8"))
    http = []
    summary = {"schema_version": 1, "started_at": utc_now(), "sources": {}}
    atomic_write(output / "summary.json", json_bytes(summary))

    def record_response(response, **_kwargs):
        url = urlsplit(response.url)
        outcome = {
            "timestamp": utc_now(), "host": url.hostname, "path": url.path,
            "status_code": response.status_code, "body_bytes": len(response.content),
            "body_sha256": digest(response.content), "content_type": response.headers.get("Content-Type"),
        }
        if url.hostname == "data.sec.gov":
            outcome["identifying_agent_matches_configuration"] = (
                response.request.headers.get("User-Agent") == os.environ.get("SEC_USER_AGENT", "").strip()
            )
        http.append(outcome)
        atomic_write(output / "http-outcomes.json", json_bytes(http))

    atomic_write(output / "http-outcomes.json", json_bytes(http))
    for name in ("fred", "sec"):
        if source not in ("all", name):
            continue
        variable = "FRED_API_KEY" if name == "fred" else "SEC_USER_AGENT"
        credential = os.environ.get(variable, "").strip()
        if not credential or (name == "sec" and not sec.valid_user_agent(credential)):
            summary["sources"][name] = {"status": "configuration_required", "variable": variable}
            continue
        with requests.Session() as session:
            session.hooks["response"].append(record_response)
            client = JsonClient(session, rate=1 if name == "fred" else 2)
            if name == "fred":
                entity = "DGS10"
                task = IngestionTask(
                    name, entity, lambda _store: (date(2024, 1, 1), date(2024, 1, 31)),
                    partial(fred.fetch, client, api_key=credential, frequency=scope["fred"]["series"][entity], snapshot=date.today()),
                )
            else:
                entity = scope["sec"]["companies"]["MSFT"]
                task = IngestionTask(
                    name, entity, lambda _store: (date(2024, 1, 1), date(2024, 6, 30)),
                    partial(sec.fetch, client, user_agent=credential, forms=set(scope["sec"]["forms"])),
                )
            runs = []
            for _attempt in range(2):
                run = run_ingestion(store, [task], mode="backfill")
                runs.append({"run_id": run["run_id"], "status": run["status"], "counts": run["counts"]})
                if run["status"] != "success":
                    break
            manifests = store.manifests(name, entity)
            try:
                reports = [inspect_batch(store, manifest) for manifest in manifests]
                repeat_written = runs[1]["counts"]["written"] if len(runs) == 2 else None
                status = "ingestion_failed"
                if len(manifests) == 2:
                    status = "validated" if repeat_written == 0 else "source_changed_review_required"
                summary["sources"][name] = {
                    "status": status,
                    "entity": entity, "runs": runs, "batches": reports,
                    "repeat_written": repeat_written,
                    "first_uncovered_date": store.coverage(name, entity, task.window(store)[0]).isoformat(),
                }
            except Exception as error:
                summary["sources"][name] = {
                    "status": "verification_failed", "error_type": type(error).__name__, "runs": runs,
                }
        atomic_write(output / "summary.json", json_bytes(summary))
    summary.update(completed_at=utc_now(), http_responses=len(http))
    atomic_write(output / "summary.json", json_bytes(summary))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("fred", "sec", "all"), default="all")
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".local" / f"live-validation-{uuid4().hex}")
    args = parser.parse_args(argv)
    try:
        summary = run_validation(args.output_dir, args.source)
    except Exception as error:
        print(f"Validation stopped ({type(error).__name__}). Use a fresh output directory under .local.")
        return 1
    print(args.output_dir.resolve() / "summary.json")
    return 0 if all(item["status"] == "validated" for item in summary["sources"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
