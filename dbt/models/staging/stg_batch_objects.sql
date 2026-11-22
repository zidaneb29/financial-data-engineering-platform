select
    p.batch_id,
    p.request_index,
    p.endpoint,
    p.retrieved_at,
    p.params_text,
    o.object_id,
    o.object_key,
    o.sha256,
    {{ field('b.receipt_text', 'identity.namespace') }} as archive_namespace
from {{ source('raw', 'batch_object') }} as p
join {{ source('ops', 'batch_load') }} as b on p.batch_id = b.batch_id
join {{ source('raw', 'source_object') }} as o on p.object_id = o.object_id
