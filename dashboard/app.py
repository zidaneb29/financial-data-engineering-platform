"""Streamlit entry point for the local financial analytics publication."""

import os
from datetime import date
from pathlib import Path

import duckdb
import streamlit as st

from dashboard import preview
from dashboard.periods import annual_periods, missing_years
from dashboard.plots import DATE_FORMATS, annual_plot, company_scale, observation_plot
from dashboard.queries import (
    Row, batch_objects, batches, fred_history, fred_observations, open_analytics,
    rows, sec_candidates, sec_groups,
)

ROOT = Path(__file__).resolve().parents[1]
PUBLICATIONS = tuple(ROOT / path for path in (
    ".local/visitor-dashboard/history.duckdb",
    ".local/visitor-dashboard/archive-sample.duckdb",
    ".local/phase4-evidence/phase3b.duckdb",
    ".local/phase5/verification/analytics.duckdb",
))
SERIES = {
    "DGS10": ("10-year Treasury yield", "The interest rate investors can earn on 10-year U.S. government debt."),
    "DGS2": ("2-year Treasury yield", "The interest rate investors can earn on 2-year U.S. government debt."),
    "FEDFUNDS": ("Federal funds rate", "The rate financial institutions pay to borrow from each other overnight, averaged over the month."),
    "CPIAUCSL": ("Consumer price index", "Tracks prices paid by urban consumers for a basket of goods and services. An increase means the basket became more expensive."),
    "UNRATE": ("Unemployment rate", "The share of people in the civilian labor force who are unemployed."),
    "GDPC1": ("Real gross domestic product", "The value of goods and services produced in the U.S., adjusted for inflation."),
}
METRICS = {
    "revenue": ("Revenue", "Income from selling goods or services before expenses, as reported by the company."),
    "operating_income": ("Operating income", "Reported profit or loss from operations."),
    "net_income": ("Net income", "The company's reported profit or loss after expenses and taxes."),
    "assets": ("Assets", "Total reported assets at the balance-sheet date."),
    "liabilities": ("Liabilities", "Total reported liabilities at the balance-sheet date."),
    "operating_cash_flow": ("Operating cash flow", "The cash generated or used by the company's regular business activities."),
    "capital_expenditures": ("Capital spending", "Cash paid for long-lived assets such as property and equipment."),
    "eps_basic": ("Basic earnings per share", "Reported profit or loss divided among common shares."),
    "eps_diluted": ("Diluted earnings per share", "Profit or loss per share after accounting for securities that could become common shares."),
}
COMPANY_NAMES = dict(zip(
    ("MSFT", "AAPL", "NVDA", "AMZN", "JPM", "GS", "BAC", "JNJ", "PFE", "WMT", "XOM", "CVX"),
    ("Microsoft", "Apple", "NVIDIA", "Amazon", "JPMorgan Chase", "Goldman Sachs", "Bank of America",
     "Johnson & Johnson", "Pfizer", "Walmart", "Exxon Mobil", "Chevron"),
    strict=True,
))
PERIODS = {
    "instant": "Point in time", "annual": "Annual", "quarter": "Standalone quarter",
    "year_to_date": "Year to date",
}


def show_table(records: list[Row], **fields: str) -> None:
    st.dataframe(
        [{label: row.get(key) for key, label in fields.items()} for row in records],
        hide_index=True, width="stretch",
    )


def show_values(
    records: list[Row], date_field: str, unit: str, date_label: str, empty_message: str,
    cadence: str = "daily", *, title: str | None = None,
) -> None:
    points = [row for row in records if row["value_number"] is not None]
    if not points:
        st.info(empty_message)
    elif len(points) <= 2:
        if len(points) == 2:
            st.caption(f"Recorded values · {unit}")
        labels = [point[date_field].strftime(DATE_FORMATS[cadence]) for point in points]
        if len(set(labels)) < len(labels):
            labels = [point[date_field].isoformat() for point in points]
        for column, point, label in zip(st.columns(len(points)), points, labels, strict=True):
            column.metric(f"{date_label} · {label}", point["value_text"], help=unit)
    else:
        st.plotly_chart(observation_plot(records, date_field, unit, date_label, cadence, title=title))
        first, last = points[0], points[-1]
        st.caption(f"First available value {first['value_text']} on {first[date_field]:%d %b %Y} · "
                   f"Latest available value {last['value_text']} on {last[date_field]:%d %b %Y}")


def filter_dates(records: list[Row], field: str, start: date, end: date) -> list[Row]:
    return [record for record in records if start <= record[field] <= end]


def date_window(start: date, end: date, key: str) -> tuple[date, date] | None:
    if start == end:
        return start, end
    selection = st.date_input("Date range", (start, end), min_value=start, max_value=end,
                              format="YYYY-MM-DD", key=key)
    if len(selection) != 2:
        st.info("Select both a start date and an end date.")
        return None
    return selection


def macro(connection: duckdb.DuckDBPyConnection, fixture_batches: set[str]) -> None:
    st.header("Economic Trends")
    st.write("Explore U.S. interest rates, prices, jobs, and economic output. Choose an indicator and a date range to see how it changed.")
    scope = rows(connection, """
        select s.series_id, s.cadence, count(o.observation_date) as observations
        from fdep_scope.series_scope s
        left join fdep_analytics.fact_economic_observations o using (series_id)
        group by all order by s.series_id
    """)
    if not scope:
        st.info("The publication contains no configured FRED series.")
        return
    coverage = {row["series_id"]: row for row in scope}
    indicator, dates = st.columns(2)
    with indicator:
        series = st.selectbox(
            "Indicator", sorted(coverage, key=lambda code: (not coverage[code]["observations"], code != "DGS10", code)),
            format_func=lambda code: SERIES.get(code, (code, ""))[0]
            + ("" if coverage[code]["observations"] else " · No archived data"),
        )
    records = fred_observations(connection, series)
    if not records:
        st.info("This indicator has no observations in the available archive. Choose another indicator to see data.")
        return

    units = sorted({row["units"] or "Unspecified" for row in records})
    unit = st.selectbox("Source unit", units) if len(units) > 1 else units[0]
    records = [row for row in records if (row["units"] or "Unspecified") == unit]
    contexts = sorted({row["seasonal_adjustment"] or "Unspecified" for row in records})
    context = st.selectbox("Seasonal adjustment", contexts) if len(contexts) > 1 else contexts[0]
    records = [row for row in records if (row["seasonal_adjustment"] or "Unspecified") == context]
    cadence = coverage[series]["cadence"]
    earliest, latest = records[0]["observation_date"], records[-1]["observation_date"]
    with dates:
        selected = date_window(earliest, latest, f"economy_{series}_{unit}_{context}_{earliest}_{latest}")
    if selected is None:
        return
    records = filter_dates(records, "observation_date", *selected)
    st.write(SERIES.get(series, (series, ""))[1])
    st.caption(f"{cadence.title()} observations · {unit} · {context}")
    if any(row["batch_id"] in fixture_batches for row in records):
        st.caption("Fixture units and seasonal adjustments are synthetic placeholders. Fixture keys are examples.")
    unavailable = sum(row["is_missing"] is True for row in records)
    withheld = sum(row["is_quarantined"] is True for row in records)
    if unavailable:
        date_label = "date" if unavailable == 1 else "dates"
        st.caption(f"FRED marked {unavailable} {date_label} as missing.")
    if withheld:
        st.caption(f"Values withheld by numeric checks · {withheld}")
    show_values(
        records, "observation_date", unit, "Observation date",
        "There are no values to display in this date range.", cadence, title=SERIES.get(series, (series, ""))[0],
    )
    st.caption("Missing values and dates FRED did not report appear as gaps. Values are from the archived copy of FRED.")
    if not records:
        return
    with st.expander("Exact values and source dates"):
        show_table(records, observation_date="Observation date", value_text="Source value", units="Source unit",
                   is_missing="Missing at source", is_quarantined="Withheld", snapshot_date="FRED vintage requested",
                   observed_at="Archive batch captured (UTC)")
    with st.expander("Source records and revisions"):
        show_table(
            records, observation_date="Observation", value_text="Source value", is_missing="Missing",
            is_quarantined="Quarantined", snapshot_date="Selected snapshot", batch_id="Batch",
            object_key="Observations object", series_metadata_key="Metadata object", source_row="Source row",
        )
        day = st.selectbox("Explore archived versions of a date", [row["observation_date"] for row in records],
                           key=f"revisions_{series}")
        history = fred_history(connection, series, day)
        winner = next(row for row in records if row["observation_date"] == day)
        for row in history:
            row["selected"] = row["batch_id"] == winner["batch_id"]
            row["archive_type"] = "Synthetic fixture" if row["batch_id"] in fixture_batches else "Source archive"
        st.caption("The committed change archive can include captures beyond the dbt publication cutoff. Unchanged captures may have no change row.")
        show_table(
            history, selected="Published selection", snapshot_date="Snapshot", value_text="Source value",
            units="Unit", is_missing="Missing", is_quarantined="Quarantined", realtime_start="Real-time start",
            realtime_end="Real-time end", batch_sequence="Sequence", batch_id="Batch",
            observed_at="Observed (UTC)", archive_type="Data origin", object_key="Raw object", source_row="Source row",
        )


def companies(connection: duckdb.DuckDBPyConnection, fixture_batches: set[str]) -> None:
    st.header("Company Performance")
    st.write("Choose a company and a financial measure to compare full financial years reported to the U.S. Securities and Exchange Commission.")
    scope = rows(connection, """
        select i.ticker, i.cik, s.batch_id, s.batch_sequence, s.observed_at, s.scope_start, s.scope_end
        from fdep_scope.issuer_scope i
        left join fdep_analytics.sec_selected_snapshots s using (cik)
        order by i.ticker
    """)
    if not scope:
        st.info("The publication contains no configured SEC issuers.")
        return
    options = {row["ticker"]: row for row in scope}
    tickers = sorted(options, key=lambda ticker: (options[ticker]["batch_id"] is None, ticker != "MSFT", ticker))
    company_selector, measure_selector = st.columns(2)
    with company_selector:
        ticker = st.selectbox(
            "Company", tickers,
            format_func=lambda t: f"{COMPANY_NAMES.get(t, t)} ({t})"
            + ("" if options[t]["batch_id"] else " · No archived data"),
        )
    snapshot = options[ticker]
    if snapshot["batch_id"] is None:
        st.info("This company has no filings in the available archive.")
        return
    if snapshot["batch_id"] in fixture_batches:
        st.caption("Synthetic demonstration values and filing details.")
    groups = sec_groups(connection, ticker)
    if not groups:
        st.info("No comparable financial reports were found for this company in the available archive.")
        return

    available = {group["metric"] for group in groups}
    metrics = [metric for metric in METRICS if metric in available]
    metrics.sort(key=lambda metric: not any(g["metric"] == metric and g["annual_ends"] for g in groups))
    with measure_selector:
        metric = st.selectbox("Financial measure", metrics, format_func=lambda key: METRICS[key][0], key=f"metric_{ticker}")
    label, description = METRICS[metric]
    st.write(description)
    choices = [group for group in groups if group["metric"] == metric]
    annual_choices = sorted(
        (group for group in choices if group["period_class"] in {"annual", "instant"}),
        key=lambda group: (-group["annual_ends"], group["tag"], group["unit"]),
    )
    group = annual_choices[0] if annual_choices else choices[0]
    if len(annual_choices) > 1:
        with st.expander("Reporting definitions"):
            st.write("Companies sometimes change how they label a measure. The comparison keeps one reporting definition throughout.")
            index = st.selectbox(
                "Source reporting definition", range(len(annual_choices)),
                format_func=lambda i: f"{annual_choices[i]['tag']} · {annual_choices[i]['unit']}",
                key=f"definition_{ticker}_{metric}",
            )
            group = annual_choices[index]
    records = sec_candidates(connection, ticker, group)
    start, end = snapshot["scope_start"], snapshot["scope_end"]
    published = annual_periods(records, start, end)
    title = f"{COMPANY_NAMES.get(ticker, ticker)} · {label}"
    if len(published) > 1:
        st.plotly_chart(annual_plot(published, title, group["unit"], range(start.year, end.year + 1)))
        first, last = published[0], published[-1]
        divisor, unit = company_scale(published, group["unit"])
        st.caption(f"{first['period_end']:%d %b %Y} · {first['value_number'] / divisor:,.2f}    "
                   f"{last['period_end']:%d %b %Y} · {last['value_number'] / divisor:,.2f} {unit.lower()}")
    elif published:
        row = published[0]
        divisor, unit = company_scale(published, group["unit"])
        st.metric(f"{label} · fiscal year ended {row['period_end']:%d %b %Y}",
                  f"{row['value_number'] / divisor:,.2f}")
        st.caption(unit)
    else:
        st.info("No comparable annual values are available for this measure in the archived period.")
    gaps = missing_years(published, start, end)
    if gaps:
        st.caption("No comparable fiscal year ending in " + ", ".join(map(str, gaps)) + ".")
    st.caption("Fiscal years follow the company's reporting calendar. Exact dates and unrounded values are below.")
    if published:
        with st.expander("Reported values and dates"):
            show_table(published, period_start="Period start", period_end="Period end",
                       value_text="Exact reported value", source_unit="Reported unit", filed_date="Filing date",
                       is_amendment="Amended filing")

    with st.expander("Filing sources and selection details"):
        st.caption(f"Archive captured {snapshot['observed_at']:%d %b %Y at %H:%M UTC} · "
                   f"Requested period ends {start} to {end} · Batch {snapshot['batch_id']}")
        selected = st.selectbox(
            "Inspect reporting definition and period type", range(len(choices)),
            index=choices.index(group), key=f"details_{ticker}_{metric}_{group['tag']}_{group['unit']}",
            format_func=lambda i: f"{choices[i]['taxonomy']}:{choices[i]['tag']} · "
            f"{PERIODS[choices[i]['period_class']]} · {choices[i]['unit']}",
        )
        detail = records if choices[selected] == group else sec_candidates(connection, ticker, choices[selected])
        show_table(detail, period_start="Period start", period_end="Period end", value_text="Source value",
                   source_unit="Reported unit", publication="Selection", filed_date="Filing date", form="Form",
                   is_amendment="Amended filing", accession_number="Accession")
        show_table(
            detail, accession_number="Accession", acceptance_datetime_text="Acceptance time",
            source_fiscal_year="Source FY", source_fiscal_period="Source FP", frame="Frame",
            is_quarantined="Quarantined", primary_document="Filing document", batch_id="Batch",
            object_key="Company Facts object", source_row="Fact row",
            filing_object_key="Submissions object", filing_source_row="Filing row",
        )


def health(connection: duckdb.DuckDBPyConnection, fixture_batches: set[str]) -> None:
    st.header("How the Data Works")
    st.write("Each number can be traced back to the original economic release or company filing.")
    collect, check, explore = st.columns(3)
    collect.markdown("**1. Collect**  \nSave the original responses from FRED and SEC EDGAR with the dates they were retrieved.")
    check.markdown("**2. Check**  \nVerify saved files, track revisions and match company figures to their filings.")
    explore.markdown("**3. Explore**  \nPrepare the comparison tables locally in DuckDB and show them in this dashboard.")
    st.caption("A separate live test transferred archived files through Amazon S3 into Snowflake. The current dashboard reads the local database.")
    ledger = batches(connection)
    snapshots = rows(connection, """
        select * from fdep_analytics.sec_selected_snapshots order by ticker
    """)
    a, b, c = st.columns(3)
    counts = {source: sum(row["source"] == source for row in ledger) for source in ("fred", "sec")}
    a.metric("Saved data batches", len(ledger), help="A batch is one successful request window for one series or company.")
    b.metric("Companies with archived filings", len(snapshots))
    c.metric("Values withheld by numeric checks", sum(row["quarantined"] or 0 for row in ledger))
    st.caption(f"{counts['fred']} economic batches · {counts['sec']} company batches")
    st.caption("The database build checks that records match the archive and that the comparison tables follow the data rules.")
    if ledger:
        with st.expander("Batch counts and validation detail"):
            show_table(
                ledger, source="Source", entity="Entity", batch_sequence="Sequence", scope_start="Window start",
                scope_end="Window end", observed_at="Observed (UTC)", committed_at="Committed (UTC)",
                requests="Requests", changes="Changes", members="Snapshot members", quarantined="Quarantined",
            )
        with st.expander("Batch and raw object lineage"):
            batch_lineage(connection, ledger, fixture_batches)
    else:
        st.info("No committed batches are visible.")
    with st.expander("Selected SEC snapshots"):
        show_table(
            snapshots, ticker="Issuer", cik="CIK", batch_sequence="Sequence", scope_start="Window start",
            scope_end="Window end", observed_at="Observed (UTC)", committed_at="Committed (UTC)",
            batch_id="Batch",
        )


def batch_lineage(
    connection: duckdb.DuckDBPyConnection, ledger: list[Row], fixture_batches: set[str],
) -> None:
    batches_by_id = {row["batch_id"]: row for row in ledger}
    batch_id = st.selectbox(
        "Inspect committed batch", list(batches_by_id),
        format_func=lambda key: (
            f"{batches_by_id[key]['source'].upper()} / {batches_by_id[key]['entity']} "
            f"| Sequence {batches_by_id[key]['batch_sequence']} | {key[:12]}"
        ),
    )
    batch = batches_by_id[batch_id]
    fixture = batch_id in fixture_batches
    st.text(f"Batch {batch_id}")
    st.text(f"Run {batch['run_id']}")
    checksum_label = "Synthetic manifest checksum placeholder" if fixture else "Recorded manifest SHA-256"
    st.text(f"{checksum_label} · {batch['manifest_hash']}")
    show_table(
        batch_objects(connection, batch_id), request_index="Request index", endpoint="Endpoint",
        retrieved_at="Retrieved (UTC)", archive_namespace="Archive", object_id="Object ID",
        object_key="Synthetic object key" if fixture else "Stored key",
        sha256="Synthetic checksum placeholder" if fixture else "Recorded object SHA-256",
    )


def public_preview() -> None:
    st.caption("Public historical preview · 2022–2024 · U.S. Treasury and SEC EDGAR")
    economy, issuers, pipeline = st.tabs(("Economic Trends", "Company Performance", "How the Data Works"))
    with economy:
        st.header("Economic Trends")
        title = SERIES["DGS10"][0]
        st.write(SERIES["DGS10"][1])
        records = preview.treasury_observations()
        selected = date_window(records[0]["observation_date"], records[-1]["observation_date"], "preview_dates")
        if selected is not None:
            visible = filter_dates(records, "observation_date", *selected)
            show_values(visible, "observation_date", "Percent", "Observation date",
                        "Treasury published no values for this date range.", title=title)
            st.caption("Calendar gaps reflect dates without a published Treasury value.")
            with st.expander("Exact values and source dates"):
                show_table(visible, observation_date="Observation date", value_text="Source value", units="Source unit")
        st.markdown(f"[U.S. Treasury daily par yield curve archive]({preview.TREASURY_SOURCE})")
    with issuers:
        st.header("Company Performance")
        st.write(METRICS["revenue"][1])
        start, end = date(2022, 1, 1), date(2024, 12, 31)
        records = annual_periods(preview.microsoft_revenue(), start, end)
        st.plotly_chart(annual_plot(records, "Microsoft · Revenue", "USD", range(start.year, end.year + 1)))
        with st.expander("Exact reported values and SEC filings"):
            show_table(records, period_start="Period start", period_end="Period end", value_text="Exact reported value",
                       source_unit="Reported unit", filed_date="Filing date", accession_number="Accession")
            for row in records:
                st.markdown(f"[Microsoft {row['period_end'].year} Form 10-K]({row['filing_url']})")
    with pipeline:
        st.header("How the Data Works")
        st.write("This preview reads two small public extracts from the repository. Treasury yields come directly from the "
                 "U.S. Treasury archive. Microsoft revenue comes from three comparable annual reports.")
        st.write("The full local pipeline archives FRED and SEC responses, validates source files, and builds DuckDB "
                 "analytics with dbt. A separate live demonstration transferred archived batches through Amazon S3 "
                 "and loaded Snowflake. The public preview runs offline.")


def main() -> None:
    st.set_page_config(page_title="U.S. Economy and Company Financials", layout="wide", initial_sidebar_state="collapsed")
    st.title("U.S. Economy and Company Financials")
    st.write("See how U.S. interest rates and other economic measures changed. Compare company performance using reports filed with the SEC.")
    configured = os.environ.get("FDEP_DUCKDB_PATH")
    path = Path(configured) if configured else next((path for path in PUBLICATIONS if path.is_file()), None)
    if path is None:
        public_preview()
        return
    try:
        with open_analytics(path) as connection:
            archives = rows(connection, """
                select batch_id, json_extract_string(receipt_text, '$.identity.namespace') as archive_namespace
                from ops.batch_load
            """)
            fixture_batches = {row["batch_id"] for row in archives if row["archive_namespace"] == "fixture"}
            if fixture_batches:
                label = "Contains synthetic demonstration data." if len(fixture_batches) < len(archives) else "Synthetic demonstration data."
                st.warning(label)
            elif archives:
                coverage = rows(connection, "select source, count(distinct entity) as entities from fdep_staging.stg_batches group by source")
                counts = {row["source"]: row["entities"] for row in coverage}
                indicators, companies_count = counts.get("fred", 0), counts.get("sec", 0)
                indicator_label = "indicator" if indicators == 1 else "indicators"
                company_label = "company" if companies_count == 1 else "companies"
                st.caption(f"Real archived data · {indicators} economic {indicator_label} · {companies_count} {company_label}")
            else:
                st.info("No source data has been archived in this database.")
            economy, issuers, pipeline = st.tabs(("Economic Trends", "Company Performance", "How the Data Works"))
            with economy:
                macro(connection, fixture_batches)
            with issuers:
                companies(connection, fixture_batches)
            with pipeline:
                health(connection, fixture_batches)
    except FileNotFoundError:
        st.error("No local dataset is available. Build or select a dataset to start exploring.")
        with st.expander("Local setup"):
            st.caption("Set FDEP_DUCKDB_PATH to a built database or create the synthetic demo.")
            st.code("python -m orchestration.local smoke .local/phase5/verification")
    except duckdb.Error as exc:
        st.error(f"The analytical database could not be queried ({type(exc).__name__}). Verify the dbt build and retry after any database writer finishes.")


if __name__ == "__main__":
    main()
