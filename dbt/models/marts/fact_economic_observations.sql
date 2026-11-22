select
    o.*,
    s.cadence
from {{ ref('stg_fred_observations') }} as o
join {{ ref('series_scope') }} as s on o.series_id = s.series_id
where {{ observed_cutoff('o.observed_at') }}
    and {{ date_cutoff('o.snapshot_date', 'fred_snapshot_through') }}
qualify row_number() over (
    partition by o.series_id, o.observation_date
    order by o.snapshot_date desc, o.batch_sequence desc, o.batch_id desc
) = 1
