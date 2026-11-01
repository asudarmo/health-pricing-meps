-- PMI-scope claim count and cost for every person-year (issues #15 and #16). A claim is one
-- in-scope event. People with no in-scope events stay in with zeros. er_stay_count and
-- er_stay_cost hold the inpatient stays that began in the emergency room (and were not birth
-- related), which are out of claim_count and claim_cost under the approved definition.
-- Costs are also on-levelled to 2023 prices with the PCE-Health factor. 2023 costs are unchanged.
with by_person as (
    select
        year,
        DUPERSID,
        count(*) filter (where in_scope) as claim_count,
        coalesce(sum(cost) filter (where in_scope), 0) as claim_cost,
        count(*) filter (where er_stay) as er_stay_count,
        coalesce(sum(cost) filter (where er_stay), 0) as er_stay_cost
    from {{ ref('int_events_pmi') }}
    group by year, DUPERSID
),

combined as (
    select
        person.year,
        person.DUPERSID,
        coalesce(by_person.claim_count, 0) as claim_count,
        coalesce(by_person.claim_cost, 0) as claim_cost,
        coalesce(by_person.er_stay_count, 0) as er_stay_count,
        coalesce(by_person.er_stay_cost, 0) as er_stay_cost,
        case when person.year = 2022 then factor.factor else 1.0 end as on_level_factor
    from {{ ref('int_person_clean') }} as person
    left join by_person
        on person.year = by_person.year and person.DUPERSID = by_person.DUPERSID
    cross join {{ ref('price_index_factor') }} as factor
)

select
    year,
    DUPERSID,
    claim_count,
    claim_cost,
    claim_cost * on_level_factor as claim_cost_2023_prices,
    er_stay_count,
    er_stay_cost,
    er_stay_cost * on_level_factor as er_stay_cost_2023_prices
from combined
