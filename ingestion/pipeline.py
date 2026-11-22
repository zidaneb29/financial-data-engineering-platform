"""Run source entities independently under one local writer lock."""

import json
import logging
from dataclasses import dataclass
from datetime import date
from time import monotonic
from typing import Callable
from uuid import uuid4

from ingestion.http import IngestionError
from ingestion.models import Record, utc_now
from storage.local import Batch, LocalStore


LOGGER = logging.getLogger(__name__)
COUNT_FIELDS = ("retrieved", "written", "duplicates", "revised")


@dataclass(frozen=True)
class IngestionTask:
    source: str
    entity: str
    window: Callable[[LocalStore], tuple[date, date]]
    fetch: Callable[[Batch], list[Record]]


def run_ingestion(store: LocalStore, tasks: list[IngestionTask], *, mode: str) -> dict:
    if not tasks or len({(task.source, task.entity) for task in tasks}) != len(tasks):
        raise ValueError("An ingestion run requires distinct source entities")
    with store.lock():
        store.recover_runs()
        started = monotonic()
        run = {
            "schema_version": 1, "run_id": uuid4().hex, "mode": mode,
            "status": "running", "started_at": utc_now(),
            "entities": [
                {"source": task.source, "entity": task.entity, "status": "pending"} for task in tasks
            ],
        }
        store.write_run(run)
        for task, result in zip(tasks, run["entities"], strict=True):
            start, end = task.window(store)
            result.update(status="running", start=start.isoformat(), end=end.isoformat())
            store.write_run(run)
            batch = Batch(store, task.source, task.entity, run["run_id"], start, end)
            entity_started = monotonic()
            try:
                records = task.fetch(batch)
                manifest = store.commit(batch, records)
            except (IngestionError, OSError) as error:
                details = (
                    {"error_code": error.code, "error": str(error)}
                    if isinstance(error, IngestionError)
                    else {"error_code": "storage_error", "error": "Local storage operation failed"}
                )
                result.update(status="failed", objects=batch.objects, **details)
            else:
                result.update(status="success", manifest=manifest["manifest"], **manifest["counts"])
            result["duration_seconds"] = round(monotonic() - entity_started, 3)
            store.write_run(run)
            logged = {key: value for key, value in result.items() if key != "objects"}
            LOGGER.info(json.dumps({"event": "entity_complete", "run_id": run["run_id"], **logged}))
        failures = sum(result["status"] == "failed" for result in run["entities"])
        run.update(
            status="success" if failures == 0 else ("failed" if failures == len(tasks) else "partial"),
            failed_entities=failures, completed_at=utc_now(),
            duration_seconds=round(monotonic() - started, 3),
            counts={key: sum(item.get(key, 0) for item in run["entities"]) for key in COUNT_FIELDS},
        )
        store.write_run(run)
        LOGGER.info(json.dumps({
            "event": "run_complete", "run_id": run["run_id"], "status": run["status"],
            "failed_entities": failures, "duration_seconds": run["duration_seconds"], **run["counts"],
        }))
        return run
