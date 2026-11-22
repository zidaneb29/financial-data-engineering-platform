"""Offline dashboard regressions against the actual dbt models."""

from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def publication(tmp_path_factory: pytest.TempPathFactory) -> Path:
    pytest.importorskip("duckdb")
    pytest.importorskip("dbt.adapters.duckdb")
    from orchestration.local import run

    directory = tmp_path_factory.mktemp("dashboard")
    run("smoke", directory)
    return directory / "analytics.duckdb"


def test_fred_revision_and_unplottable_values(publication: Path) -> None:
    from dashboard.queries import fred_history, fred_observations, open_analytics

    with open_analytics(publication) as connection:
        observations = fred_observations(connection, "DGS10")
        assert [(r["value_text"], r["is_missing"], r["is_quarantined"]) for r in observations] == [
            ("4.25", False, False), (None, True, False), ("0.0000000000001", False, True),
        ]
        history = fred_history(connection, "DGS10", observations[0]["observation_date"])
        assert [r["batch_sequence"] for r in history] == [2, 1]
        assert history[0]["batch_id"] == observations[0]["batch_id"]
        assert not fred_observations(connection, "DGS10' OR true --")


def test_sec_periods_amendments_ambiguity_and_lineage(publication: Path) -> None:
    from dashboard.queries import batch_objects, batches, open_analytics, sec_candidates, sec_groups

    with open_analytics(publication) as connection:
        groups = {(r["tag"], r["period_class"]): r for r in sec_groups(connection, "MSFT")}
        annual = sec_candidates(connection, "MSFT", groups["Revenues", "annual"])
        quarter = sec_candidates(connection, "MSFT", groups["Revenues", "quarter"])
        assert len({r["period_start"] for r in annual + quarter}) > 1
        assert [r["is_amendment"] for r in annual if r["publication"] == "Published"] == [True]
        assert "Earlier filing" in {r["publication"] for r in annual}
        ambiguous_group = next(group for (tag, _), group in groups.items() if tag == "SalesRevenueNet")
        ambiguous = sec_candidates(connection, "MSFT", ambiguous_group)
        assert "Ambiguous latest filing date" in {r["publication"] for r in ambiguous}
        assert "Published" not in {r["publication"] for r in ambiguous}
        assert not sec_groups(connection, "CVX")
        ledger = {r["batch_id"]: r for r in batches(connection)}
        chosen = next(r for r in annual if r["publication"] == "Published")
        objects = batch_objects(connection, chosen["batch_id"])
        assert len(objects) == ledger[chosen["batch_id"]]["requests"]
        assert any(r["object_key"].endswith(chosen["object_key"]) for r in objects)


def test_plot_uses_only_recorded_numeric_points() -> None:
    pytest.importorskip("duckdb")
    pytest.importorskip("plotly")
    from dashboard.plots import observation_plot

    first, missing, last = (date(2024, 1, day) for day in (1, 2, 10))
    figure = observation_plot([
        {"observation_date": first, "value_number": Decimal("1.25"), "value_text": "1.250"},
        {"observation_date": missing, "value_number": None, "value_text": None},
        {"observation_date": last, "value_number": Decimal("0"), "value_text": "0"},
    ], "observation_date", "Percent", "Observation date")
    trace = figure.data[0]
    assert list(trace.x) == [first, last]
    assert list(trace.y) == [1.25, 0]
    assert trace.customdata[0][0] == "1.250"
    assert trace.mode == "markers"


def test_monthly_line_breaks_for_explicit_and_absent_observations() -> None:
    pytest.importorskip("duckdb")
    pytest.importorskip("plotly")
    from dashboard.plots import observation_plot

    jan, feb, mar, may, june = (date(2024, month, 1) for month in (1, 2, 3, 5, 6))
    records = [{"day": day, "value_number": value, "value_text": str(value)}
               for day, value in zip((jan, feb, mar, may, june), (1, None, 0, 2, 3), strict=True)]
    figure = observation_plot(records, "day", "Index", "Observation date", "monthly")
    assert list(figure.data[0].x) == [jan, mar, may, june]
    assert list(figure.data[1].x) == [jan, None, mar, None, may, june]
    assert list(figure.data[1].y) == [1, None, 0, None, 2, 3]
    assert not figure.data[1].connectgaps


def test_annual_comparison_preserves_dates_units_and_missing_years() -> None:
    pytest.importorskip("duckdb")
    pytest.importorskip("plotly")
    from dashboard.periods import annual_periods, missing_years
    from dashboard.plots import annual_plot

    def report(year: int, **overrides) -> dict:
        return dict(
            {"period_start": date(year - 1, 7, 1), "period_end": date(year, 6, 30),
             "form": "10-K", "publication": "Published", "period_class": "annual",
             "value_number": Decimal("1234567890.23"), "value_text": "1234567890.23", "source_unit": "USD"},
            **overrides,
        )

    start, end = date(2019, 1, 1), date(2024, 12, 31)
    records = [report(2019), report(2020, period_class="quarter", form="10-Q"),
               report(2021, form="10-K/A"), report(2022, publication="Earlier filing"),
               report(2023), report(2023, period_end=date(2023, 7, 1)), report(2024)]
    published = annual_periods(records, start, end)
    assert [row["period_end"].year for row in published] == [2019, 2021, 2024]
    assert missing_years(published, start, end) == [2020, 2022, 2023]
    chart = annual_plot(published, "Company revenue", "USD", range(2019, 2025))
    assert list(chart.data[0].x) == ["2019", "2021", "2024"]
    assert list(chart.layout.xaxis.categoryarray) == [str(year) for year in range(2019, 2025)]
    assert chart.layout.yaxis.title.text == "Billions of US dollars"
    assert list(chart.data[0].customdata[0]) == ["2019-06-30", "1234567890.23", "USD"]
    assert annual_periods([report(2019), report(2020, period_start=date(2019, 6, 29))], start, end) == []


@pytest.mark.parametrize("cadence, tickformat", [
    ("daily", "%d %b %Y"), ("monthly", "%b %Y"), ("quarterly", "%b %Y"),
])
def test_date_ticks_are_calendar_dates(cadence: str, tickformat: str) -> None:
    pytest.importorskip("duckdb")
    pytest.importorskip("plotly")
    from dashboard.plots import observation_plot

    day = date(2024, 1, 1)
    chart = observation_plot([{"day": day, "value_number": 1, "value_text": "1.0"}],
                             "day", "Percent", "Date", cadence)
    assert chart.layout.xaxis.tickformat == tickformat
    assert chart.layout.xaxis.range == (date(2023, 12, 31), date(2024, 1, 2))
    assert chart.data[0].x == (day,)
    assert "%{x|%Y-%m-%d}" in chart.data[0].hovertemplate


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_sparse_rendering(count: int, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("duckdb")
    pytest.importorskip("plotly")
    pytest.importorskip("streamlit")
    from dashboard import app

    interface = MagicMock()
    interface.columns.side_effect = lambda size: [MagicMock() for _ in range(size)]
    monkeypatch.setattr(app, "st", interface)
    records = [{"day": date(2024, 1, i), "value_number": i, "value_text": f"{i}.000"}
               for i in range(1, count + 1)]
    records.append({"day": date(2024, 1, 31), "value_number": None, "value_text": None})
    app.show_values(records, "day", "USD", "Date", "No values")
    assert interface.plotly_chart.call_count == int(count >= 3)
    assert interface.info.call_count == int(count == 0)
    if count in (1, 2):
        metrics = interface.columns.side_effect = [MagicMock() for _ in range(count)]
        interface.columns.side_effect = None
        interface.columns.return_value = metrics
        app.show_values(records, "day", "USD", "Date", "No values")
        for i, column in enumerate(metrics, start=1):
            column.metric.assert_called_once_with(f"Date · 0{i} Jan 2024", f"{i}.000", help="USD")


@pytest.mark.parametrize("fixture", [True, False])
def test_lineage_labels(fixture: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("duckdb")
    pytest.importorskip("plotly")
    pytest.importorskip("streamlit")
    from dashboard import app

    interface = MagicMock()
    interface.selectbox.return_value = "batch"
    monkeypatch.setattr(app, "st", interface)
    digest = "fixture-hash" if fixture else "a" * 64
    key = "fixture/raw/file.json" if fixture else "archive/raw/file.json"
    monkeypatch.setattr(app, "batch_objects", lambda *_: [{"sha256": digest, "object_key": key}])
    app.batch_lineage(MagicMock(), [{"batch_id": "batch", "run_id": "run", "manifest_hash": digest}],
                      {"batch"} if fixture else set())
    checksum = "Synthetic checksum placeholder" if fixture else "Recorded object SHA-256"
    object_key = "Synthetic object key" if fixture else "Stored key"
    assert interface.dataframe.call_args.args[0][0][checksum] == digest
    assert interface.dataframe.call_args.args[0][0][object_key] == key
    label = "Synthetic manifest checksum placeholder" if fixture else "Recorded manifest SHA-256"
    interface.text.assert_any_call(f"{label} · {digest}")


def test_dashboard_navigation_and_read_only(publication: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("plotly")
    pytest.importorskip("streamlit")
    from dashboard import app

    interface = MagicMock()
    interface.selectbox.side_effect = lambda label, options, **kwargs: (
        "CVX" if label == "Company" else next(iter(options))
    )
    interface.date_input.side_effect = lambda _label, value, **kwargs: value
    interface.tabs.return_value = [MagicMock() for _ in range(3)]
    interface.columns.side_effect = lambda count: [MagicMock() for _ in range(count)]
    monkeypatch.setattr(app, "st", interface)

    monkeypatch.setenv("FDEP_DUCKDB_PATH", str(publication))
    before = sha256(publication.read_bytes()).digest()
    app.main()
    interface.error.assert_not_called()
    interface.tabs.assert_called_once_with(("Economic Trends", "Company Performance", "How the Data Works"))
    interface.warning.assert_called_once_with("Synthetic demonstration data.")
    interface.date_input.assert_called_once()
    assert any("seasonal adjustments are synthetic" in call.args[0] for call in interface.caption.call_args_list)
    assert any("No comparable financial reports" in call.args[0] for call in interface.info.call_args_list)
    assert "Synthetic checksum placeholder" in interface.dataframe.call_args_list[-2].args[0][0]
    assert sha256(publication.read_bytes()).digest() == before

    missing = publication.with_name("missing.duckdb")
    monkeypatch.setenv("FDEP_DUCKDB_PATH", str(missing))
    app.main()
    assert "No local dataset" in interface.error.call_args.args[0]
    assert not missing.exists()


def test_window_is_inclusive_and_partial_widget_selection_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("duckdb")
    pytest.importorskip("plotly")
    pytest.importorskip("streamlit")
    from dashboard import app

    interface = MagicMock()
    first, middle, end = (date(2024, 1, day) for day in (1, 10, 31))
    monkeypatch.setattr(app, "st", interface)
    records = [{"day": day} for day in (first, middle, end)]
    assert app.filter_dates(records, "day", middle, end) == records[1:]
    interface.date_input.return_value = (middle,)
    assert app.date_window(first, end, "range") is None
    interface.info.assert_called_once()


def test_public_preview_renders_two_genuine_trends_without_a_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("duckdb")
    pytest.importorskip("plotly")
    pytest.importorskip("streamlit")
    from dashboard import app

    interface = MagicMock()
    interface.tabs.return_value = [MagicMock() for _ in range(3)]
    interface.date_input.side_effect = lambda _label, value, **_options: value
    monkeypatch.delenv("FDEP_DUCKDB_PATH", raising=False)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.setattr(app, "PUBLICATIONS", (tmp_path / "missing.duckdb",))
    monkeypatch.setattr(app, "st", interface)
    monkeypatch.setattr(app, "open_analytics", MagicMock(side_effect=AssertionError("Unexpected database access")))

    app.main()

    assert any("Public historical preview" in call.args[0] for call in interface.caption.call_args_list)
    yield_plot, revenue_plot = [call.args[0] for call in interface.plotly_chart.call_args_list]
    assert len(yield_plot.data[0].x) == 749
    assert yield_plot.data[0].x[0] == date(2022, 1, 3)
    assert yield_plot.data[0].x[-1] == date(2024, 12, 31)
    assert yield_plot.layout.yaxis.title.text == "Percent"
    assert not yield_plot.data[1].connectgaps
    assert list(revenue_plot.data[0].x) == ["2022", "2023", "2024"]
    assert list(revenue_plot.data[0].y) == [198.27, 211.915, 245.122]
    assert revenue_plot.layout.yaxis.title.text == "Billions of US dollars"
    assert list(revenue_plot.data[0].customdata[-1]) == ["2024-06-30", "245122000000", "USD"]
    assert sum("sec.gov/Archives" in call.args[0] for call in interface.markdown.call_args_list) == 3
    assert not list(tmp_path.iterdir())
