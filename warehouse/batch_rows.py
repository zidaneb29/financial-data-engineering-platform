"""Project validated archive records to the shared RAW warehouse contract."""

from typing import Any

from ingestion.sec import read_snapshot
from storage.local import LocalStore, json_bytes
from storage.manifest import require
from storage.transfer import PreparedBatch
from warehouse.numeric import NumericRangeError, checked_decimal


TEXT_LIMIT = 16_777_216


def payload_text(value: Any) -> str:
    text = json_bytes(value).decode("utf-8").rstrip("\n")
    require(len(text.encode("utf-8")) <= TEXT_LIMIT, "Payload exceeds the RAW text-size contract")
    return text


def batch_records(store: LocalStore, batch: PreparedBatch) -> tuple[list[tuple], list[tuple], list[tuple]]:
    snapshot = read_snapshot(store, batch.manifest) if batch.manifest["source"] == "sec" else []
    changes, members, quarantine = [], [], []
    for kind, rows, output in (
        ("change", batch.rows, changes), ("snapshot", snapshot, members),
    ):
        ordinals: dict[str, int] = {}
        for row in rows:
            dataset = row["dataset"]
            ordinal = ordinals.get(dataset, 0)
            ordinals[dataset] = ordinal + 1
            value = row.get("value")
            text = payload_text(row)
            try:
                number = checked_decimal(value)
            except NumericRangeError:
                number = None
                quarantine.append((batch.batch_id, kind, ordinal, value, "numeric_range", text))
            output.append((
                batch.batch_id, dataset, ordinal, batch.manifest["source"],
                batch.manifest["entity"], text, value, number,
            ))
    return changes, members, quarantine
