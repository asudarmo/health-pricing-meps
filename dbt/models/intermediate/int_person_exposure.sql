-- Exposure (years in scope) for each person-year, at month resolution (issue #13).
-- A calendar month counts when it lies inside the reference period of a round in which the
-- person is eligible (ELGRND = 1). Reference periods that start before the year count from
-- January and those that end after it count to December. A person who is in a round's household
-- unit for only part of the year, a birth or a death for example, gets fewer months. A gap round
-- (ELGRND = 4, not in a household unit) adds no months. The derivation is logged in
-- _docs/decisions.md.
with rounds as (
    select year, DUPERSID, ELGRND31 as eligible, BEGRFY31 as begin_year, BEGRFM31 as begin_month,
           ENDRFY31 as end_year, ENDRFM31 as end_month
    from {{ ref('int_person_clean') }}
    union all
    select year, DUPERSID, ELGRND42, BEGRFY42, BEGRFM42, ENDRFY42, ENDRFM42
    from {{ ref('int_person_clean') }}
    union all
    select year, DUPERSID, ELGRND53, BEGRFY53, BEGRFM53, ENDRFY53, ENDRFM53
    from {{ ref('int_person_clean') }}
),

months_in_scope as (
    select rounds.year, rounds.DUPERSID, months.month
    from rounds
    cross join generate_series(1, 12) as months(month)
    where rounds.eligible = 1
        and rounds.begin_year * 12 + rounds.begin_month <= rounds.year * 12 + months.month
        and rounds.end_year * 12 + rounds.end_month >= rounds.year * 12 + months.month
    group by all
),

counted as (
    select year, DUPERSID, count(*) as exposure_months
    from months_in_scope
    group by all
)

select
    person.year,
    person.DUPERSID,
    coalesce(counted.exposure_months, 0) as exposure_months,
    coalesce(counted.exposure_months, 0) / 12.0 as exposure
from {{ ref('int_person_clean') }} as person
left join counted
    on person.year = counted.year and person.DUPERSID = counted.DUPERSID
