select
    f.*,
    s.ticker,
    s.observed_at,
    s.committed_at,
    s.scope_start,
    s.scope_end,
    p.object_key as filing_object_key,
    p.source_row as filing_source_row,
    p.primary_document,
    p.acceptance_datetime_text,
    p.report_date
from {{ ref('stg_sec_facts') }} as f
join {{ ref('sec_selected_snapshots') }} as s on f.batch_id = s.batch_id and f.cik = s.cik
join {{ ref('stg_sec_filings') }} as p
    on f.batch_id = p.batch_id and f.cik = p.cik and f.accession_number = p.accession_number
    and f.form = p.form and f.filed_date = p.filing_date and f.period_end = p.report_date
where f.selection_eligible and f.taxonomy = 'us-gaap'
    and {{ date_cutoff('f.filed_date', 'sec_filed_through') }}
    and (
        (f.unit = 'USD' and f.metric in ('assets', 'liabilities')
            and f.period_class = 'instant' and f.period_start is null)
        or (f.unit = 'USD' and f.metric not in ('assets', 'liabilities', 'eps_basic', 'eps_diluted')
            and f.period_class in ('annual', 'quarter', 'year_to_date') and f.period_start is not null)
        or (f.unit = 'USD/shares' and f.metric in ('eps_basic', 'eps_diluted')
            and f.period_class in ('annual', 'quarter', 'year_to_date') and f.period_start is not null)
    )
