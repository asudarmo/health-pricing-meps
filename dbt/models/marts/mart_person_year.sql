-- The modelling table: one row per person-year in the modelling population, 2022 and 2023
-- (issue #17). Rating factor candidates, exposure, PMI-scope claim count and cost, and the survey
-- weight. Column roles are declared in schema.yml and tested in tests/test_mart.py. Race, income
-- and education are not in this table. Sex and the flags marked analysis_only are for analysis and
-- must never enter the final rating structure.
select
    person.DUPERSID,
    person.DUID,
    person.year,
    -- 2022 households are split train or test, all of 2023 is the out-of-time set
    case
        when person.year = 2023 then 'out_of_time'
        else {{ household_split('person.DUID') }}
    end as split,

    -- Rating factor candidates
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
    person.DIABDX_M18,

    -- Analysis only
    person.SEX,
    person.age_source,
    person.age_topcoded,
    person.region_source,
    person.left_survey_early,
    person.VARSTR,
    person.VARPSU,
    claims.er_stay_count,
    claims.er_stay_cost,
    claims.er_stay_cost_2023_prices,

    -- Exposure, claims and weight
    person.exposure,
    claims.claim_count,
    claims.claim_cost,
    claims.claim_cost_2023_prices,
    person.perwt
from {{ ref('int_person_retained') }} as person
inner join {{ ref('int_person_claims') }} as claims
    on person.year = claims.year and person.DUPERSID = claims.DUPERSID
