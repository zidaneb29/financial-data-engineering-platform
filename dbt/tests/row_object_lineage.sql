with references_to_check as (
    select batch_id, object_key from {{ ref('stg_fred_observations') }}
    union all
    select batch_id, series_metadata_key from {{ ref('stg_fred_observations') }}
    union all
    select batch_id, object_key from {{ ref('stg_sec_members') }}
)
select r.*
from references_to_check as r
where not exists (
    select 1 from {{ ref('stg_batch_objects') }} as o
    where o.batch_id = r.batch_id and o.object_key = concat(o.archive_namespace, '/', r.object_key)
)
