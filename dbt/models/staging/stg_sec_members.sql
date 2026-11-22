select
    r.batch_id,
    r.row_ordinal,
    r.dataset,
    r.entity as cik,
    r.payload_text,
    r.value_text,
    r.value_number,
    {{ field('r.payload_text', 'accession_number') }} as accession_number,
    {{ field('r.payload_text', 'object_key') }} as object_key,
    cast({{ field('r.payload_text', 'source_row') }} as bigint) as source_row,
    {{ field('r.payload_text', 'form') }} as form,
    cast({{ field('r.payload_text', 'is_amendment') }} as boolean) as is_amendment
from {{ source('raw', 'sec_snapshot_member') }} as r
join {{ ref('stg_batches') }} as b
    on r.batch_id = b.batch_id and r.source = b.source and r.entity = b.entity
where r.source = 'sec'
