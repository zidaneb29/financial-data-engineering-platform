"""FRED metadata and paginated observation ingestion."""

from datetime import date, timedelta

from ingestion.http import JsonClient, PayloadError
from ingestion.models import Record, decimal_text, source_date
from storage.local import Batch


BASE = "https://api.stlouisfed.org/fred"


def incremental_start(configured: date, first_uncovered: date, end: date, lookback_days: int) -> date:
    lookback = end - timedelta(days=min(lookback_days - 1, end.toordinal() - 1))
    return max(configured, min(first_uncovered, lookback))


def fetch(
    client: JsonClient, batch: Batch, *, api_key: str, frequency: str,
    snapshot: date, page_size: int = 1000,
) -> list[Record]:
    fixed = {
        "series_id": batch.entity, "file_type": "json",
        "realtime_start": snapshot.isoformat(), "realtime_end": snapshot.isoformat(),
    }
    metadata = client.get(f"{BASE}/series", params={**fixed, "api_key": api_key}, fred=True)
    metadata_key = batch.archive("series", metadata, fixed)
    series = metadata.data.get("seriess")
    if not isinstance(series, list) or len(series) != 1 or not isinstance(series[0], dict):
        raise PayloadError("FRED series metadata must contain one series")
    info = series[0]
    units = info.get("units")
    seasonal_adjustment = info.get("seasonal_adjustment")
    if info.get("id") != batch.entity or not isinstance(units, str) or not units:
        raise PayloadError("FRED series metadata has an unexpected ID or missing units")
    if str(info.get("frequency", "")).lower() != frequency:
        raise PayloadError("FRED series frequency differs from configured cadence")
    if seasonal_adjustment is not None and not isinstance(seasonal_adjustment, str):
        raise PayloadError("FRED series seasonal adjustment must be text")

    batch.metadata.update(snapshot_date=snapshot.isoformat(), series_metadata_key=metadata_key)
    fixed.update(
        observation_start=batch.start.isoformat(), observation_end=batch.end.isoformat(),
        units="lin", order_by="observation_date", sort_order="asc", limit=page_size,
    )
    records = []
    total = None
    last_date = None
    while total is None or len(records) < total:
        offset = len(records)
        params = {**fixed, "offset": offset}
        response = client.get(
            f"{BASE}/series/observations", params={**params, "api_key": api_key}, fred=True,
        )
        object_key = batch.archive("observations", response, params)
        count = response.data.get("count")
        rows = response.data.get("observations")
        returned_offset = response.data.get("offset")
        if (
            type(count) is not int or count < 0 or (total is not None and count != total)
            or type(returned_offset) is not int or returned_offset != offset
            or not isinstance(rows, list) or len(rows) > min(page_size, count - offset)
            or (not rows and offset < count)
        ):
            raise PayloadError("Invalid FRED pagination counts or offsets")
        total = count
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise PayloadError("FRED observation must be an object")
            observed = source_date(row.get("date"), "observation date")
            realtime_start = source_date(row.get("realtime_start"), "real-time start")
            realtime_end = source_date(row.get("realtime_end"), "real-time end")
            if (
                not batch.start <= observed <= batch.end or (last_date and observed <= last_date)
                or not realtime_start <= snapshot <= realtime_end
            ):
                raise PayloadError("FRED observations are out of window, order, or vintage")
            last_date = observed
            day = observed.isoformat()
            missing = row.get("value") == "."
            fields = {
                "series_id": batch.entity, "observation_date": day, "units": units,
                "frequency": frequency, "is_missing": missing,
                "value": None if missing else decimal_text(row.get("value"), from_text=True),
                "seasonal_adjustment": seasonal_adjustment,
            }
            records.append(Record("observations", (day,), fields, {
                "snapshot_date": snapshot.isoformat(), "realtime_start": realtime_start.isoformat(),
                "realtime_end": realtime_end.isoformat(), "object_key": object_key,
                "source_row": index, "series_metadata_key": metadata_key,
            }))
    return records
