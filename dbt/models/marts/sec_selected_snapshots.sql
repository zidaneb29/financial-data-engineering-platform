select
    b.batch_id,
    b.entity as cik,
    s.ticker,
    b.batch_sequence,
    b.scope_start,
    b.scope_end,
    b.observed_at,
    b.committed_at
from {{ ref('stg_batches') }} as b
join {{ ref('issuer_scope') }} as s on b.entity = s.cik
where b.source = 'sec' and {{ observed_cutoff('b.observed_at') }}
qualify row_number() over (
    partition by b.entity
    order by b.batch_sequence desc, b.batch_id desc
) = 1
