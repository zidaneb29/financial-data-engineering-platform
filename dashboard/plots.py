"""Plot source points without filling gaps or merging reporting contexts."""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

import plotly.graph_objects as go

from dashboard.queries import Row


DATE_FORMATS = {"daily": "%d %b %Y", "monthly": "%b %Y", "quarterly": "%b %Y"}


def source_period(day: date, cadence: str) -> int:
    if cadence == "daily":
        return day.toordinal()
    months = day.year * 12 + day.month - 1
    return months // 3 if cadence == "quarterly" else months


def observation_plot(
    records: Sequence[Row], date_field: str, unit: str, date_label: str, cadence: str = "daily",
    *, title: str | None = None,
) -> go.Figure:
    points = [row for row in records if row["value_number"] is not None]
    dates = [row[date_field] for row in points]
    detail_field = "period_start" if date_field == "period_end" else "snapshot_date"
    detail_label = "Period start" if date_field == "period_end" else "Snapshot"
    details = [
        [row["value_text"], f"<br>{detail_label} · {row[detail_field]}" if row.get(detail_field) else ""]
        for row in points
    ]
    figure = go.Figure(go.Scatter(
        x=dates,
        y=[float(row["value_number"]) for row in points],
        customdata=details,
        mode="markers",
        marker={"color": "#087f8c", "size": 5 if len(points) > 80 else 8},
        hovertemplate="%{x|%Y-%m-%d}<br>%{customdata[0]}%{customdata[1]}<extra></extra>",
    ))
    if len(points) >= 3:
        segment_dates = []
        segment_values = []
        previous = None
        for day, row in zip(dates, points, strict=True):
            period = source_period(day, cadence)
            if previous is not None and period != previous + 1:
                segment_dates.append(None)
                segment_values.append(None)
            segment_dates.append(day)
            segment_values.append(float(row["value_number"]))
            previous = period
        figure.add_scatter(
            x=segment_dates, y=segment_values, mode="lines", line={"color": "#087f8c", "width": 1.7},
            showlegend=False, hoverinfo="skip", connectgaps=False,
        )
        figure.update_layout(showlegend=False)
    figure.update_layout(
        title=title, height=350, margin={"l": 20, "r": 20, "t": 58 if title else 16, "b": 18},
        xaxis={
            "title": date_label, "type": "date", "tickformat": DATE_FORMATS[cadence],
            "range": [dates[0] - timedelta(days=1), dates[0] + timedelta(days=1)]
            if dates and min(dates) == max(dates) else None,
        },
        yaxis={"title": unit, "automargin": True},
    )
    return figure


def company_scale(records: Sequence[Row], unit: str) -> tuple[Decimal, str]:
    if unit == "USD/shares":
        return Decimal(1), "US dollars per share"
    if unit == "USD":
        if max(abs(row["value_number"]) for row in records) >= 1_000_000_000:
            return Decimal(1_000_000_000), "Billions of US dollars"
        return Decimal(1_000_000), "Millions of US dollars"
    return Decimal(1), unit


def annual_plot(
    records: Sequence[Row], title: str, unit: str, years: Sequence[int],
) -> go.Figure:
    divisor, axis_unit = company_scale(records, unit)
    figure = go.Figure(go.Bar(
        x=[str(row["period_end"].year) for row in records],
        y=[float(row["value_number"] / divisor) for row in records],
        customdata=[[str(row["period_end"]), row["value_text"], row["source_unit"]] for row in records],
        marker_color="#087f8c",
        hovertemplate=(
            "Fiscal year ended %{customdata[0]}<br>%{customdata[1]} %{customdata[2]}<extra></extra>"
        ),
    ))
    figure.update_layout(
        title=title, height=350, margin={"l": 20, "r": 20, "t": 58, "b": 18},
        xaxis={
            "title": "Year in which the fiscal period ended",
            "type": "category", "categoryorder": "array", "categoryarray": [str(year) for year in years],
        },
        yaxis={"title": axis_unit, "automargin": True, "rangemode": "tozero"},
    )
    return figure
