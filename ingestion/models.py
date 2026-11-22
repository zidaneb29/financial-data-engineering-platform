"""Shared normalized records and validation primitives."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from ingestion.http import PayloadError


@dataclass(frozen=True)
class Record:
    dataset: str
    key: tuple
    fields: dict[str, Any]
    lineage: dict[str, Any]
    comparison_key: tuple | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def source_date(value: Any, field: str) -> date:
    try:
        parsed = date.fromisoformat(value)
        if value != parsed.isoformat():
            raise ValueError
        return parsed
    except (TypeError, ValueError):
        raise PayloadError(f"Invalid source date in {field}") from None


def decimal_text(value: Any, *, from_text: bool = False) -> str:
    allowed = (str,) if from_text else (Decimal, int)
    if not isinstance(value, allowed) or isinstance(value, bool):
        raise PayloadError("Unexpected type for financial value")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise PayloadError("Invalid financial value") from None
    if not number.is_finite() or abs(number.adjusted()) > 1000:
        raise PayloadError("Financial value is non-finite or outside supported magnitude")
    if not number:
        return "0"
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
