-- One row per person-year per benefit type, for the stacked candidate model (issue #24).
-- Benefit types are inpatient_daycase (inpatient stays, and outpatient or office-based visits where a
-- surgical procedure was performed) and outpatient (all other in-scope visits). Every person-year in
-- mart_person_year has both rows, with zeros where there are no in-scope events. Event counts and
-- costs add up to claim_count, claim_cost and claim_cost_2023_prices in mart_person_year.
with benefit_types as (
    select 'inpatient_daycase' as benefit_type
    union all
    select 'outpatient'
),

events as (
    select
        year,
        DUPERSID,
        benefit_type,
        count(*) as event_count,
        sum(cost) as cost
    from {{ ref('int_events_pmi') }}
    where in_scope
    group by year, DUPERSID, benefit_type
)

select
    person.DUPERSID,
    person.DUID,
    person.year,
    person.split,
    benefit_types.benefit_type,
    person.exposure,
    coalesce(events.event_count, 0) as event_count,
    cast(coalesce(events.event_count, 0) > 0 as integer) as claimant,
    coalesce(events.cost, 0) as cost,
    coalesce(events.cost, 0) * case when person.year = 2022 then factor.factor else 1.0 end
        as cost_2023_prices,
    person.age,
    person.region,
    person.inscov,
    person.rthlth,
    person.mnhlth,
    person.OFTSMK53,
    person.PHYEXE53,
    person.HIBPDX,
    person.CHDDX,
    person.ANGIDX,
    person.MIDX,
    person.OHRTDX,
    person.STRKDX,
    person.CHOLDX,
    person.CANCERDX,
    person.ARTHDX,
    person.ASTHDX,
    person.DIABDX_M18
from {{ ref('mart_person_year') }} as person
cross join benefit_types
cross join {{ ref('price_index_factor') }} as factor
left join events
    on person.year = events.year
    and person.DUPERSID = events.DUPERSID
    and benefit_types.benefit_type = events.benefit_type
