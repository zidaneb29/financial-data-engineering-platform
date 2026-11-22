select
    batch_id,
    manifest_hash,
    {{ field('manifest_text', 'source') }} as source,
    {{ field('manifest_text', 'entity') }} as entity,
    {{ field('manifest_text', 'run_id') }} as run_id,
    cast(split_part(split_part({{ field('manifest_text', 'manifest') }}, '/', 5), '.', 1) as bigint) as batch_sequence,
    cast({{ field('manifest_text', 'start') }} as date) as scope_start,
    cast({{ field('manifest_text', 'end') }} as date) as scope_end,
    cast({{ field('manifest_text', 'completed_at') }} as {{ timestamp_type() }}) as observed_at,
    committed_at
from {{ source('ops', 'batch_load') }}
