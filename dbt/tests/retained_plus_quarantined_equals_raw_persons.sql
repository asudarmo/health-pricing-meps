-- Every raw person-year is either in the modelling population or in quarantine, never both and
-- never neither (issue #14).
with raw_counts as (
    select 2022 as year, count(*) as persons from {{ ref('stg_fyc_2022') }}
    union all
    select 2023, count(*) from {{ ref('stg_fyc_2023') }}
),

split as (
    select year, count(*) as persons from {{ ref('int_person_retained') }} group by year
    union all
    select year, count(*) from {{ ref('quarantine_person') }} group by year
),

totals as (
    select year, sum(persons) as persons from split group by year
)

select raw_counts.year, raw_counts.persons as raw_persons, totals.persons as split_persons
from raw_counts
left join totals on raw_counts.year = totals.year
where totals.persons is distinct from raw_counts.persons
