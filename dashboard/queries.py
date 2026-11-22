"""Queries against the Phase 4 local dbt contract."""

from collections.abc import Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterator

import duckdb

Row = dict[str, Any]


@contextmanager
def open_analytics(path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = duckdb.connect(str(path), read_only=True, config={"threads": 2})
    try:
        yield connection
    finally:
        connection.close()


def rows(
    connection: duckdb.DuckDBPyConnection, sql: str, parameters: Sequence[object] = ()
) -> list[Row]:
    result = connection.execute(sql, parameters)
    columns = [column[0].lower() for column in result.description]
    return [
        {
            key: value.astimezone(UTC)
            if isinstance(value, datetime) and value.tzinfo is not None else value
            for key, value in zip(columns, record, strict=True)
        }
        for record in result.fetchall()
    ]


def fred_observations(connection: duckdb.DuckDBPyConnection, series: str) -> list[Row]:
    return rows(connection, """
        select * from fdep_analytics.fact_economic_observations
        where series_id = ? order by observation_date
    """, (series,))


def fred_history(connection: duckdb.DuckDBPyConnection, series: str, day: date) -> list[Row]:
    return rows(connection, """
        select * from fdep_staging.stg_fred_observations
        where series_id = ? and observation_date = ?
        order by snapshot_date desc, batch_sequence desc, batch_id desc
    """, (series, day))


def sec_groups(connection: duckdb.DuckDBPyConnection, ticker: str) -> list[Row]:
    return rows(connection, """
        select c.metric, c.taxonomy, c.tag, c.unit, c.period_class,
            count(distinct case when starts_with(c.form, '10-K') then f.period_end end) as annual_ends
        from fdep_analytics.sec_financial_candidates c
        left join fdep_analytics.fact_company_financials f using (batch_id, row_ordinal)
        where c.ticker = ?
        group by all order by c.metric, c.taxonomy, c.tag, c.unit, c.period_class
    """, (ticker,))


def sec_candidates(
    connection: duckdb.DuckDBPyConnection, ticker: str, group: Row
) -> list[Row]:
    return rows(connection, """
        select c.*, case
            when f.batch_id is not null then 'Published'
            when c.filed_date < max(c.filed_date) over period then 'Earlier filing'
            when count(*) over filing > 1 then 'Ambiguous latest filing date'
            when c.value_number is null then 'No numeric projection'
            else 'Unpublished'
        end as publication
        from fdep_analytics.sec_financial_candidates c
        left join fdep_analytics.fact_company_financials f
            on c.batch_id = f.batch_id and c.row_ordinal = f.row_ordinal
        where c.ticker = ? and c.metric = ? and c.taxonomy = ? and c.tag = ?
            and c.unit = ? and c.period_class = ?
        window period as (partition by c.period_start, c.period_end),
            filing as (partition by c.period_start, c.period_end, c.filed_date)
        order by c.period_end, c.period_start, c.filed_date desc, c.accession_number
    """, (ticker, *(group[k] for k in ("metric", "taxonomy", "tag", "unit", "period_class"))))


def batches(connection: duckdb.DuckDBPyConnection) -> list[Row]:
    return rows(connection, """
        select b.*,
            cast(json_extract(l.counts_text, '$.requests') as bigint) as requests,
            cast(json_extract(l.counts_text, '$.changes') as bigint) as changes,
            cast(json_extract(l.counts_text, '$.members') as bigint) as members,
            cast(json_extract(l.counts_text, '$.quarantined') as bigint) as quarantined
        from fdep_staging.stg_batches b
        join ops.batch_load l on b.batch_id = l.batch_id
        order by b.observed_at desc, b.batch_sequence desc, b.batch_id
    """)


def batch_objects(connection: duckdb.DuckDBPyConnection, batch_id: str) -> list[Row]:
    return rows(connection, """
        select request_index, endpoint, retrieved_at, archive_namespace, object_id, object_key, sha256
        from fdep_staging.stg_batch_objects where batch_id = ? order by request_index
    """, (batch_id,))



