import json
from datetime import date
from functools import partial

import pytest

from ingestion import sec
from ingestion.pipeline import IngestionTask, run_ingestion
from storage.local import LocalStore
from conftest import response


CIK = "0000789019"
OTHER_CIK = "0000320193"
ORIGINAL = "0000789019-24-000001"
AMENDMENT = "0000789019-24-000002"
QUARTER = "0000789019-24-000003"
LATER = "0000789019-25-000001"
START = date(2019, 1, 1)
END = date(2024, 12, 31)
FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}
USER_AGENT = "Financial Data Test operator@example.test"


def columns(*rows):
    fields = ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")
    columns = {name: [] for name in fields}
    for row in rows:
        for key, value in zip(fields, row, strict=True):
            columns[key].append(value)
    return columns


def submissions(*rows, cik=CIK, files=()):
    return response({"cik": cik, "filings": {"recent": columns(*rows), "files": list(files)}})


def facts(tags, *, cik=CIK):
    return response({"cik": int(cik), "facts": {"us-gaap": {
        tag: {"units": units} for tag, units in tags.items()
    }, "issuer-extension": {"SpecialMetric": {"units": {"USD": []}}}}})


def fact(value=100, **overrides):
    return {
        "start": "2023-07-01", "end": "2024-06-30", "val": value, "accn": ORIGINAL,
        "form": "10-K", "filed": "2024-07-25", "fy": 2024, "fp": "FY", **overrides,
    }


def task(client, cik=CIK):
    return IngestionTask(
        "sec", cik, lambda _store: (START, END),
        partial(sec.fetch, client, user_agent=USER_AGENT, forms=FORMS),
    )


ORIGINAL_FILING = (ORIGINAL, "2024-07-25", "2024-06-30", "10-K", "form-k.htm")
AMENDMENT_FILING = (AMENDMENT, "2024-09-01", "2024-06-30", "10-K/A", "amended.htm")
QUARTER_FILING = (QUARTER, "2024-10-25", "2024-09-30", "10-Q", "quarter.htm")
LATER_FILING = (LATER, "2025-07-25", "2025-06-30", "10-K", "later.htm")


def test_submissions_archives_facts_units_and_periods(tmp_path, fake_http):
    archive = {"name": f"CIK{CIK}-submissions-001.json", "filingTo": "2024-07-25"}
    page = submissions(AMENDMENT_FILING, QUARTER_FILING, LATER_FILING, files=[archive])
    annual = fact()
    quarter = fact(
        34, start="2024-07-01", end="2024-09-30", accn=QUARTER, form="10-Q",
        filed="2024-10-25", fp="Q1", fy=2025,
    )
    assets = {key: value for key, value in annual.items() if key != "start"}
    later = fact(101, accn=LATER, filed="2025-07-25", fy=2025)
    companyfacts = facts({
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"USD": [annual, annual, quarter, later], "EUR": [annual]},
        "Assets": {"USD": [assets]},
        "EarningsPerShareBasic": {"USD/shares": [fact(1.23)]},
    })
    client, calls = fake_http([page, response(columns(ORIGINAL_FILING)), companyfacts])
    store = LocalStore(tmp_path)
    run = run_ingestion(store, [task(client)], mode="backfill")
    assert run["counts"] == {"retrieved": 11, "written": 10, "duplicates": 1, "revised": 0}
    batch = store.manifests("sec", CIK)[0]
    rows = list(store.rows([batch]))
    assert len([row for row in rows if row["dataset"] == "filings"]) == 4
    assert {row["period_class"] for row in rows if row["dataset"] == "facts"} == {"instant", "annual", "quarter"}
    assert next(row for row in rows if row.get("unit") == "EUR")["selection_eligible"] is False
    eps = next(row for row in rows if row.get("metric") == "eps_basic")
    assert eps["value"] == "1.23" and eps["filing_matched"]
    assert eps["accession_number"] == ORIGINAL and eps["namespace"] == "us-gaap"
    assert eps["fiscal_year"] == 2024 and eps["fiscal_period"] == "FY"
    assert (tmp_path / eps["object_key"]).read_bytes() == companyfacts.content
    assert all(item["headers"]["User-Agent"] == USER_AGENT for item in calls)
    assert [item["time"] for item in calls] == [0, 0.5, 1]
    assert calls[1]["url"].endswith(archive["name"])
    assert "operating_income" in batch["metadata"]["missing_mapped_metrics"]
    assert USER_AGENT not in json.dumps(run) + json.dumps(batch)
    assert "issuer-extension" in (tmp_path / eps["object_key"]).read_text()


def test_revisions_amendments_conflicts_and_as_of_selection(tmp_path, fake_http):
    store = LocalStore(tmp_path)
    page = submissions(ORIGINAL_FILING, AMENDMENT_FILING)
    amended = fact(120, accn=AMENDMENT, form="10-K/A", filed="2024-09-01")
    conflicting = {**amended, "val": 121}
    for candidates, expected in [
        ([fact()], (3, 0, 0)),
        ([fact(), amended, conflicting], (2, 3, 2)),
        ([fact(), amended, conflicting], (0, 5, 0)),
    ]:
        client, _ = fake_http([page, facts({"Revenues": {"USD": candidates}})])
        run = run_ingestion(store, [task(client)], mode="incremental")
        assert tuple(run["counts"][key] for key in ("written", "duplicates", "revised")) == expected
    batches = store.manifests("sec", CIK)
    rows = list(store.rows(batches))
    filings = [row for row in rows if row["dataset"] == "filings"]
    facts_rows = [row for row in rows if row["dataset"] == "facts"]
    assert len({row["object_key"] for row in facts_rows}) == 2
    assert batches[1]["metadata"]["conflicting_fact_keys"] == 1
    assert {row["is_amendment"] for row in facts_rows} == {False, True}
    original, = sec.select_period_candidates(facts_rows, filings, filed_through=END, original=True)
    assert original["value"] == "100" and not original["ambiguous"]
    prior, = sec.select_period_candidates(facts_rows, filings, filed_through=date(2024, 8, 1))
    assert prior["value"] == "100"
    latest, = sec.select_period_candidates(facts_rows, filings, filed_through=END)
    assert latest["ambiguous"] and latest["value"] is None
    observed, = sec.select_period_candidates(
        facts_rows, filings, filed_through=END, observed_through=batches[0]["completed_at"],
    )
    assert observed["value"] == "100"


def test_failed_issuer_preserves_other_issuer_and_retries_later(tmp_path, fake_http):
    store = LocalStore(tmp_path)
    client, _ = fake_http([
        submissions(ORIGINAL_FILING), response(status=503), response(status=503),
        submissions(cik=OTHER_CIK), facts({}, cik=OTHER_CIK),
    ], attempts=2)
    run = run_ingestion(store, [task(client), task(client, OTHER_CIK)], mode="incremental")
    assert run["status"] == "partial" and run["failed_entities"] == 1
    assert run["entities"][0]["error_code"] == "http_503"
    assert len(run["entities"][0]["objects"]) == 1
    assert not store.manifests("sec", CIK)
    assert len(store.manifests("sec", OTHER_CIK)) == 1
    client, _ = fake_http([submissions(ORIGINAL_FILING), facts({})])
    assert run_ingestion(store, [task(client)], mode="incremental")["status"] == "success"
    assert len(list(tmp_path.glob(f"raw/sec/{CIK}/submissions/*.json"))) == 1


def test_column_misalignment_fails_before_company_facts(tmp_path, fake_http):
    bad_page = {"cik": CIK, "filings": {"recent": columns(ORIGINAL_FILING), "files": []}}
    bad_page["filings"]["recent"]["reportDate"].clear()
    client, calls = fake_http([response(bad_page)])
    store = LocalStore(tmp_path)
    run = run_ingestion(store, [task(client)], mode="backfill")
    assert run["entities"][0]["error_code"] == "invalid_payload"
    assert len(calls) == 1 and not store.manifests("sec", CIK)


def test_unmatched_fact_is_retained_and_becomes_selectable_when_filing_arrives(tmp_path, fake_http):
    store = LocalStore(tmp_path)
    financials = facts({"Revenues": {"USD": [fact()]}})
    client, _ = fake_http([submissions(), financials])
    run_ingestion(store, [task(client)], mode="incremental")
    client, _ = fake_http([submissions(ORIGINAL_FILING), financials])
    run_ingestion(store, [task(client)], mode="incremental")
    batches = store.manifests("sec", CIK)
    assert [batch["metadata"]["unmatched_fact_rows"] for batch in batches] == [1, 0]
    rows = list(store.rows(batches))
    financial, = [row for row in rows if row["dataset"] == "facts"]
    filing, = [row for row in rows if row["dataset"] == "filings"]
    assert financial["filing_matched"] is False
    selected, = sec.select_period_candidates([financial], [filing], filed_through=END)
    assert selected["value"] == "100"


def test_period_classifier_distinguishes_ytd_and_odd_durations():
    assert sec.period_class(date(2024, 1, 1), date(2024, 6, 30), "10-Q") == "year_to_date"
    assert sec.period_class(date(2024, 1, 1), date(2024, 6, 30), "10-K") == "other_duration"
    assert sec.period_class(date(2024, 1, 1), date(2024, 2, 20), "10-Q") == "other_duration"


def test_user_agent_requires_identifying_contact():
    assert sec.valid_user_agent(USER_AGENT)
    assert not sec.valid_user_agent("python-requests/2.x")
    assert not sec.valid_user_agent("operator@example.test")
    assert not sec.valid_user_agent("Broken\nAgent operator@example.test")


def test_snapshot_replay_excludes_withdrawn_facts_without_erasing_history(tmp_path, fake_http):
    store = LocalStore(tmp_path)
    page = submissions(ORIGINAL_FILING)
    for candidate in ([fact(), fact()], []):
        client, _ = fake_http([page, facts({"Revenues": {"USD": candidate}})])
        run_ingestion(store, [task(client)], mode="incremental")
    first, latest = store.manifests("sec", CIK)
    assert [row["value"] for row in sec.read_snapshot(store, first) if row["dataset"] == "facts"] == ["100"]
    assert [row["dataset"] for row in sec.read_snapshot(store, latest)] == ["filings"]
    assert [row["value"] for row in store.rows([first, latest]) if row["dataset"] == "facts"] == ["100"]
    raw_object = tmp_path / latest["objects"][-1]["object_key"]
    raw_object.write_bytes(b"{}")
    with pytest.raises(OSError, match="checksum"):
        sec.read_snapshot(store, latest)


def test_filing_with_missing_report_date_preserves_amendment(tmp_path, fake_http):
    missing_report = (AMENDMENT, "2024-09-01", "", "10-K/A", "amended.htm")
    amendment = fact(102, accn=AMENDMENT, form="10-K/A", filed="2024-09-01")
    client, _ = fake_http([submissions(missing_report), facts({"Revenues": {"USD": [amendment]}})])
    store = LocalStore(tmp_path)
    assert run_ingestion(store, [task(client)], mode="backfill")["status"] == "success"
    filing, financial = sorted(
        store.rows(store.manifests("sec", CIK)), key=lambda row: row["dataset"], reverse=True,
    )
    assert filing["report_date"] is None and filing["is_amendment"]
    assert financial["filing_matched"] and financial["is_amendment"]


def test_snapshot_selection_excludes_withdrawn_amendment_and_preserves_original_history(tmp_path, fake_http):
    store = LocalStore(tmp_path)
    page = submissions(ORIGINAL_FILING, AMENDMENT_FILING)
    amendment = fact(120, accn=AMENDMENT, form="10-K/A", filed="2024-09-01")
    for candidates in ([fact(), amendment], [fact()], []):
        client, _ = fake_http([page, facts({"Revenues": {"USD": candidates}})])
        assert run_ingestion(store, [task(client)], mode="incremental")["status"] == "success"
    first, second, empty = store.manifests("sec", CIK)
    history = list(store.rows([first, second, empty]))
    cumulative, = sec.select_period_candidates(
        [row for row in history if row["dataset"] == "facts"],
        [row for row in history if row["dataset"] == "filings"], filed_through=END,
    )
    assert cumulative["value"] == "120"  # Historical candidate, absent from newer snapshots.
    selected = sec.select_snapshot_candidates(store, CIK, filed_through=END)
    assert selected["manifest"] == empty["manifest"] and selected["candidates"] == []
    selected = sec.select_snapshot_candidates(store, CIK, filed_through=END, manifest=second)
    candidate, = selected["candidates"]
    assert candidate["value"] == "100"
    selected = sec.select_snapshot_candidates(store, CIK, filed_through=END, manifest=first, original=True)
    candidate, = selected["candidates"]
    assert candidate["value"] == "100"
    selected = sec.select_snapshot_candidates(store, CIK, filed_through=END, observed_through=first["completed_at"])
    candidate, = selected["candidates"]
    assert candidate["value"] == "120"
    selected = sec.select_snapshot_candidates(
        store, CIK, filed_through=date(2024, 8, 1), manifest=first,
    )
    candidate, = selected["candidates"]
    assert candidate["value"] == "100"
    assert {row["accession_number"] for row in history if row["dataset"] == "facts"} == {ORIGINAL, AMENDMENT}
    assert sec.select_snapshot_candidates(
        store, CIK, filed_through=END, observed_through="2000-01-01T00:00:00+00:00",
    )["manifest"] is None


def test_snapshot_membership_restores_reappearing_fact_and_keeps_conflicts(tmp_path, fake_http):
    store = LocalStore(tmp_path)
    page = submissions(ORIGINAL_FILING)
    for candidates in ([fact()], [], [fact(), fact(101)]):
        client, _ = fake_http([page, facts({"Revenues": {"USD": candidates}})])
        run_ingestion(store, [task(client)], mode="incremental")
    batches = store.manifests("sec", CIK)
    assert batches[-1]["counts"]["duplicates"] == 2
    latest = sec.select_snapshot_candidates(store, CIK, filed_through=END)
    candidate, = latest["candidates"]
    assert candidate["ambiguous"] and candidate["value"] is None
    rows = sec.read_snapshot(store, batches[-1])
    assert {row["value"] for row in rows if row["dataset"] == "facts"} == {"100", "101"}


def test_explicit_snapshot_cutoff_and_entity_are_enforced(tmp_path, fake_http):
    from storage.manifest import IntegrityError

    store = LocalStore(tmp_path)
    client, _ = fake_http([submissions(ORIGINAL_FILING), facts({"Revenues": {"USD": [fact()]}})])
    run_ingestion(store, [task(client)], mode="incremental")
    manifest, = store.manifests("sec", CIK)
    with pytest.raises(IntegrityError):
        sec.select_snapshot_candidates(
            store, CIK, filed_through=END, manifest=manifest,
            observed_through="2000-01-01T00:00:00+00:00",
        )
    with pytest.raises(IntegrityError):
        sec.select_snapshot_candidates(store, OTHER_CIK, filed_through=END, manifest=manifest)
