"""Conservative comparisons for one company, concept, and source unit."""

from collections import defaultdict
from datetime import date

from dashboard.queries import Row


def annual_periods(records: list[Row], start: date, end: date) -> list[Row]:
    """Return one actual comparable report per calendar year of the fiscal end."""
    by_year: dict[int, list[Row]] = defaultdict(list)
    for row in records:
        if (
            row["publication"] == "Published"
            and row["value_number"] is not None
            and row["form"] in {"10-K", "10-K/A"}
            and row["period_class"] in {"annual", "instant"}
        ):
            by_year[row["period_end"].year].append(row)
    unique = [values[0] for _, values in sorted(by_year.items()) if len(values) == 1]
    overlapping = set()
    for earlier, later in zip(unique, unique[1:]):
        if later["period_start"] is not None and later["period_start"] <= earlier["period_end"]:
            overlapping.update((earlier["period_end"], later["period_end"]))
    return [row for row in unique if row["period_end"] not in overlapping and start <= row["period_end"] <= end]


def missing_years(records: list[Row], start: date, end: date) -> list[int]:
    present = {row["period_end"].year for row in records}
    return sorted(set(range(start.year, end.year + 1)) - present)
