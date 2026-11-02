-- For every person-year, event counts and costs summed over benefit types equal claim_count, claim_cost
-- and claim_cost_2023_prices in mart_person_year (issue #24). Costs are compared to within a millionth
-- of a dollar, because float sums can differ in the last digits. Returns the person-years that differ.
with summed as (
    select
        year,
        DUPERSID,
        sum(event_count) as event_count,
        sum(cost) as cost,
        sum(cost_2023_prices) as cost_2023_prices
    from {{ ref('mart_person_year_benefit') }}
    group by year, DUPERSID
)

select mart.year, mart.DUPERSID
from {{ ref('mart_person_year') }} as mart
inner join summed
    on mart.year = summed.year and mart.DUPERSID = summed.DUPERSID
where mart.claim_count <> summed.event_count
    or abs(mart.claim_cost - summed.cost) > 1e-6
    or abs(mart.claim_cost_2023_prices - summed.cost_2023_prices) > 1e-6
