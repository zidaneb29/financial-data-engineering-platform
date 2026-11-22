select
    r.batch_id,
    r.row_ordinal,
    b.batch_sequence,
    b.observed_at,
    b.committed_at,
    {{ field('r.payload_text', 'series_id') }} as series_id,
    cast({{ field('r.payload_text', 'observation_date') }} as date) as observation_date,
    cast({{ field('r.payload_text', 'snapshot_date') }} as date) as snapshot_date,
    cast({{ field('r.payload_text', 'realtime_start') }} as date) as realtime_start,
    cast({{ field('r.payload_text', 'realtime_end') }} as date) as realtime_end,
    {{ field('r.payload_text', 'units') }} as units,
    {{ field('r.payload_text', 'frequency') }} as frequency,
    {{ field('r.payload_text', 'seasonal_adjustment') }} as seasonal_adjustment,
    cast({{ field('r.payload_text', 'is_missing') }} as boolean) as is_missing,
    r.value_text,
    r.value_number,
    r.value_text is not null and r.value_number is null as is_quarantined,
    {{ field('r.payload_text', 'object_key') }} as object_key,
    {{ field('r.payload_text', 'series_metadata_key') }} as series_metadata_key,
    cast({{ field('r.payload_text', 'source_row') }} as bigint) as source_row
from {{ source('raw', 'ingestion_record') }} as r
join {{ ref('stg_batches') }} as b
    on r.batch_id = b.batch_id and r.source = b.source and r.entity = b.entity
where r.source = 'fred' and r.dataset = 'observations'
