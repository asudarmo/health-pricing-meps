-- One row per person-year for 2022 and 2023, with every reserved code given an explicit treatment.
-- The rules and their reasons are in _docs/decisions.md (2026-11-01, reserved-code treatment).
with stacked as (
    select * from {{ ref('stg_fyc_2022') }}
    union all by name
    select * from {{ ref('stg_fyc_2023') }}
),

aged as (
    select
        *,
        -- Year-end age where valid, else age at the last eligible round (people who left part-way)
        case when age >= 0 then age else case when AGELAST >= 0 then AGELAST end end as age_clean,
        case
            when age >= 0 then 'year_end'
            when AGELAST >= 0 then 'last_eligible'
        end as age_source,
        -- Year-end region where valid, else the latest round with a valid region (people who left
        -- part-way), the pattern approved for any characteristic with a year-end -1
        case
            when region between 1 and 4 then region
            when REGION53 between 1 and 4 then REGION53
            when REGION42 between 1 and 4 then REGION42
            when REGION31 between 1 and 4 then REGION31
        end as region_clean,
        case
            when region between 1 and 4 then 'year_end'
            when REGION53 between 1 and 4 then 'last_round'
            when REGION42 between 1 and 4 then 'last_round'
            when REGION31 between 1 and 4 then 'last_round'
        end as region_source
    from stacked
),

recoded as (
    select
        * exclude (age, region),
        age_clean as age,
        region_clean as region
    from aged
)

select
    year,
    DUID,
    PID,
    DUPERSID,
    PANEL,
    VARSTR,
    VARPSU,
    famid,
    perwt,
    age,
    age_source,
    age = 85 as age_topcoded,
    {{ null_reserved('SEX') }} as SEX,
    region,
    region_source,
    -- Analysis only, never a rating factor. True when the person was no longer eligible at the
    -- end of the year, which is why their year-end age and region were -1.
    ELGRND = 3 as left_survey_early,
    {{ null_reserved('inscov') }} as inscov,
    {{ latest_round('RTHLTH') }} as rthlth,
    {{ latest_round_source('RTHLTH') }} as rthlth_round,
    {{ latest_round('MNHLTH') }} as mnhlth,
    {{ latest_round_source('MNHLTH') }} as mnhlth_round,
    {{ category_level('OFTSMK53', true) }} as OFTSMK53,
    {{ yes_no_level('PHYEXE53', true) }} as PHYEXE53,
    {% for flag in ['HIBPDX', 'CHDDX', 'ANGIDX', 'MIDX', 'OHRTDX', 'STRKDX', 'CHOLDX', 'CANCERDX', 'ARTHDX'] %}
    {{ yes_no_level(flag, true) }} as {{ flag }},
    {% endfor %}
    {{ yes_no_level('ASTHDX') }} as ASTHDX,
    {{ yes_no_level('DIABDX_M18') }} as DIABDX_M18,
    {{ null_reserved('ASSTIL31') }} as ASSTIL31,
    -- Round dates and eligibility feed the exposure measure (#13), which needs -1 (not in round)
    {% for stem in ['BEGRFM', 'BEGRFY', 'ENDRFM', 'ENDRFY', 'ELGRND'] %}
    {% for rnd in [31, 42, 53] %}
    {{ null_reserved(stem ~ rnd, '-15, -8, -7') }} as {{ stem }}{{ rnd }},
    {% endfor %}
    {% endfor %}
    {{ null_reserved('ENDRFM', '-15, -8, -7') }} as ENDRFM,
    {{ null_reserved('ENDRFY', '-15, -8, -7') }} as ENDRFY,
    {{ null_reserved('ELGRND', '-15, -8, -7') }} as ELGRND,
    {% for count in ['OBTOTV', 'OPTOTV', 'ERTOT', 'IPDIS', 'OBDRV'] %}
    {{ null_reserved(count, '-15') }} as {{ count }},
    {% endfor %}
    IPNGTD,
    RXTOT,
    {% for cost in ['TOTEXP', 'TOTSLF', 'TOTMCR', 'TOTMCD', 'TOTPRV', 'TOTPTR', 'OBVEXP', 'OBDEXP', 'OPTEXP', 'ERTEXP', 'IPTEXP', 'RXEXP'] %}
    {{ cost }}{{ "," if not loop.last }}
    {% endfor %}
from recoded
