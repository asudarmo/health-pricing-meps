-- Person-years held out of the modelling population, with the first matching reason (issue #14).
-- Stays in the git-ignored DuckDB file. Nothing here is published.
select
    year,
    DUPERSID,
    DUID,
    case
        when duplicate_person_year then 'duplicate_person_year'
        when no_exposure then 'no_exposure'
        when missing_core_factor then 'missing_core_factor'
        when negative_expenditure then 'negative_expenditure'
        when not_in_analytic_population then 'not_in_person_level_analytic_population'
    end as reason_code,
    case
        when duplicate_person_year then 'duplicate person-year'
        when no_exposure then 'no exposure'
        when missing_core_factor then 'missing age, sex, region or coverage'
        when negative_expenditure then 'negative expenditure'
        when not_in_analytic_population then 'not in person-level analytic population'
    end as reason,
    perwt,
    exposure,
    TOTEXP
from {{ ref('int_person_flags') }}
where duplicate_person_year or no_exposure or missing_core_factor or negative_expenditure
    or not_in_analytic_population
