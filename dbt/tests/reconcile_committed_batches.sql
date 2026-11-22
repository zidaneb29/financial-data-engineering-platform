with counts as (
    select batch_id, 'changes' as kind, count(*) as actual
    from {{ source('raw', 'ingestion_record') }} group by batch_id
    union all
    select batch_id, 'members', count(*)
    from {{ source('raw', 'sec_snapshot_member') }} group by batch_id
    union all
    select batch_id, 'requests', count(*)
    from {{ ref('stg_batch_objects') }} group by batch_id
    union all
    select batch_id, 'quarantined', count(*)
    from {{ source('raw', 'numeric_quarantine') }} group by batch_id
),
expected as (
    {% for kind in ['changes', 'members', 'requests', 'quarantined'] %}
    select batch_id, '{{ kind }}' as kind,
        cast({{ field('counts_text', kind) }} as bigint) as expected
    from {{ source('ops', 'batch_load') }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)
select coalesce(e.batch_id, c.batch_id) as batch_id, coalesce(e.kind, c.kind) as kind
from expected as e
full outer join counts as c on e.batch_id = c.batch_id and e.kind = c.kind
where e.expected is null or e.expected <> coalesce(c.actual, 0)


