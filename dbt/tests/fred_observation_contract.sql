select *
from {{ ref('stg_fred_observations') }}
where (is_missing and (value_text is not null or value_number is not null))
    or (not is_missing and value_text is null)
    or realtime_start is null or realtime_end is null
    or snapshot_date not between realtime_start and realtime_end
