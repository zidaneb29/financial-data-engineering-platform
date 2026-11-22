import hashlib
from datetime import date
from functools import partial

import pytest

from ingestion import fred
from ingestion.pipeline import IngestionTask, run_ingestion
from storage.local import LocalStore
from conftest import response


START = date(2024, 1, 1)
END = date(2024, 2, 1)
SNAPSHOT = date(2024, 3, 1)


def metadata():
    return response({"seriess": [{
        "id": "FEDFUNDS", "frequency": "Monthly", "units": "Percent",
        "title": "Federal Funds Effective Rate", "seasonal_adjustment": "Not Seasonally Adjusted",
    }]})


def observation(day, value, snapshot=SNAPSHOT):
    return {
        "date": day, "value": value, "realtime_start": snapshot.isoformat(),
        "realtime_end": snapshot.isoformat(),
    }


def page(offset, count, *observations):
    return response({"offset": offset, "count": count, "observations": list(observations)})


def task(client, *, snapshot=SNAPSHOT, start=START, end=END):
    return IngestionTask(
        "fred", "FEDFUNDS", lambda _store: (start, end),
        partial(fred.fetch, client, api_key="do-not-save", frequency="monthly", snapshot=snapshot, page_size=1),
    )


def test_paginated_ingestion_preserves_zero_missing_and_source_bytes(tmp_path, fake_http):
    first = page(0, 2, observation("2024-01-01", "0.000"))
    client, calls = fake_http([metadata(), first, page(1, 2, observation("2024-02-01", "."))], rate=1)
    store = LocalStore(tmp_path)
    run = run_ingestion(store, [task(client)], mode="backfill")
    batches = store.manifests("fred", "FEDFUNDS")
    batch = batches[0]
    rows = list(store.rows(batches))
    assert run["counts"] == {"retrieved": 2, "written": 2, "duplicates": 0, "revised": 0}
    assert [(row["value"], row["is_missing"]) for row in rows] == [("0", False), (None, True)]
    assert rows[0]["units"] == "Percent" and rows[0]["frequency"] == "monthly"
    assert rows[0]["source"] == "fred" and rows[0]["series_id"] == "FEDFUNDS"
    assert rows[0]["ingestion_timestamp"].endswith("+00:00")
    assert [call["params"]["offset"] for call in calls[1:]] == [0, 1]
    assert [call["time"] for call in calls] == [0, 1, 2]
    assert (tmp_path / rows[0]["object_key"]).read_bytes() == first.content
    assert batch["objects"][1]["sha256"] == hashlib.sha256(first.content).hexdigest()
    assert "offset" not in batch["objects"][0]["params"]
    assert all(b"do-not-save" not in path.read_bytes() for path in tmp_path.rglob("*.json"))


@pytest.mark.parametrize("second_page", [
    page(1, 2), page(0, 2, observation("2024-02-01", "1")),
    page(1, 2, observation("2024-01-01", "1")),
    page(1, 3, observation("2024-02-01", "1")),
    page(1, 2, observation("2024-02-01", "not numeric")),
])
def test_incomplete_or_invalid_pagination_never_advances_coverage(tmp_path, fake_http, second_page):
    client, _ = fake_http([metadata(), page(0, 2, observation("2024-01-01", "1")), second_page])
    store = LocalStore(tmp_path)
    run = run_ingestion(store, [task(client)], mode="backfill")
    assert run["status"] == "failed"
    assert run["entities"][0]["error_code"] == "invalid_payload"
    assert len(run["entities"][0]["objects"]) == 3
    assert store.coverage("fred", "FEDFUNDS", START) == START
    assert not list(store.rows(store.manifests("fred", "FEDFUNDS")))


def test_replay_revision_reversion_and_empty_window(tmp_path, fake_http):
    store = LocalStore(tmp_path)
    for value, expected in [("1.20", (1, 0, 0)), ("1.2", (0, 1, 0)), ("1.3", (1, 0, 1)), ("1.2", (1, 0, 1))]:
        client, _ = fake_http([metadata(), page(0, 1, observation("2024-01-01", value))])
        counts = run_ingestion(store, [task(client)], mode="incremental")["counts"]
        assert (counts["written"], counts["duplicates"], counts["revised"]) == expected
    client, _ = fake_http([metadata(), page(0, 0)])
    empty = run_ingestion(store, [task(client)], mode="backfill")
    assert empty["status"] == "success" and empty["counts"]["retrieved"] == 0
    rows = list(store.rows(store.manifests("fred", "FEDFUNDS")))
    assert [row["value"] for row in rows] == ["1.2", "1.3", "1.2"]
    assert len({row["object_key"] for row in rows}) == 3


def test_incremental_recovers_gaps_and_overlaps_recent_observations(tmp_path, fake_http):
    store = LocalStore(tmp_path)
    client, _ = fake_http([metadata(), page(0, 0)])
    run_ingestion(store, [task(client, start=END)], mode="backfill")
    assert store.coverage("fred", "FEDFUNDS", START) == START
    client, _ = fake_http([metadata(), page(0, 0)])
    run_ingestion(store, [task(client, end=date(2024, 1, 31))], mode="backfill")
    uncovered = store.coverage("fred", "FEDFUNDS", START)
    assert uncovered == date(2024, 2, 2)
    assert fred.incremental_start(START, uncovered, date(2024, 2, 8), 5) == uncovered
    assert fred.incremental_start(START, uncovered, date(2024, 2, 3), 5) == date(2024, 1, 30)


def test_unchanged_later_snapshot_retains_archive_without_duplicate_rows(tmp_path, fake_http):
    store = LocalStore(tmp_path)
    for day in (SNAPSHOT, date(2024, 3, 2)):
        client, _ = fake_http([metadata(), page(0, 1, observation("2024-01-01", "1.125", day))])
        run_ingestion(store, [task(client, snapshot=day)], mode="incremental")
    first, second = store.manifests("fred", "FEDFUNDS")
    assert first["objects"][1]["sha256"] != second["objects"][1]["sha256"]
    assert second["metadata"]["snapshot_date"] == "2024-03-02"
    assert second["normalized"] == {}
    assert len(list(store.rows([first, second]))) == 1
