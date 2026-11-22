with latest as (
    select *
    from {{ ref('sec_financial_candidates') }}
    qualify dense_rank() over (
        partition by cik, taxonomy, tag, unit, period_class, period_start, period_end
        order by filed_date desc
    ) = 1
),
checked as (
    select *,
        count(*) over (
            partition by cik, taxonomy, tag, unit, period_class, period_start, period_end
        ) as latest_candidate_count
    from latest
)
select *
from checked
where latest_candidate_count = 1 and value_number is not null
