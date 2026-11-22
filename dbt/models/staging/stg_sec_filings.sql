select
    batch_id,
    row_ordinal,
    cik,
    accession_number,
    object_key,
    source_row,
    form,
    is_amendment,
    cast({{ field('payload_text', 'filing_date') }} as date) as filing_date,
    cast({{ field('payload_text', 'report_date') }} as date) as report_date,
    {{ field('payload_text', 'primary_document') }} as primary_document,
    {{ field('payload_text', 'filing_metadata.acceptanceDateTime') }} as acceptance_datetime_text
from {{ ref('stg_sec_members') }}
where dataset = 'filings'
