-- Every exclusion rule, by year (issue #14). Rules overlap, so persons_flagged can add to more than
-- the persons quarantined. persons_quarantined counts each person once, under the first reason.
-- Rules that remove more than 1% of persons or of cost need the user's decision (gate 3) and say
-- so in gate3_decision.
with rules as (
    select
        'duplicate_person_year' as rule_code,
        'duplicate person-year' as description,
        'data_quality' as kind
    union all select 'no_exposure', 'no exposure', 'data_quality'
    union all select 'missing_core_factor', 'missing age, sex, region or coverage', 'data_quality'
    union all select 'negative_expenditure', 'negative expenditure', 'data_quality'
    union all select
        'not_in_person_level_analytic_population',
        'not in person-level analytic population (zero person weight)',
        'population_definition'
),

years as (
    select year, count(*) as persons, sum(TOTEXP) as totexp
    from {{ ref('int_person_flags') }}
    group by year
),

flagged as (
    select year, 'duplicate_person_year' as rule_code, count(*) as persons, sum(TOTEXP) as cost
    from {{ ref('int_person_flags') }} where duplicate_person_year group by year
    union all
    select year, 'no_exposure', count(*), sum(TOTEXP)
    from {{ ref('int_person_flags') }} where no_exposure group by year
    union all
    select year, 'missing_core_factor', count(*), sum(TOTEXP)
    from {{ ref('int_person_flags') }} where missing_core_factor group by year
    union all
    select year, 'negative_expenditure', count(*), sum(TOTEXP)
    from {{ ref('int_person_flags') }} where negative_expenditure group by year
    union all
    select year, 'not_in_person_level_analytic_population', count(*), sum(TOTEXP)
    from {{ ref('int_person_flags') }} where not_in_analytic_population group by year
),

quarantined as (
    select year, reason_code as rule_code, count(*) as persons_quarantined
    from {{ ref('quarantine_person') }}
    group by year, reason_code
)

select
    years.year,
    rules.rule_code,
    rules.description,
    rules.kind,
    coalesce(flagged.persons, 0) as persons_flagged,
    coalesce(quarantined.persons_quarantined, 0) as persons_quarantined,
    coalesce(flagged.persons, 0) * 1.0 / years.persons as share_of_persons,
    coalesce(flagged.cost, 0) * 1.0 / years.totexp as share_of_totexp,
    coalesce(flagged.cost, 0) as totexp_flagged,
    -- Decision gate 3: only the modelling population definition has been decided so far
    case
        when coalesce(flagged.persons, 0) * 1.0 / years.persons <= 0.01
            and coalesce(flagged.cost, 0) * 1.0 / years.totexp <= 0.01
            then 'not needed (1% or less)'
        when rules.rule_code = 'not_in_person_level_analytic_population'
            then 'approved 2026-11-01'
        else 'needs user decision'
    end as gate3_decision
from years
cross join rules
left join flagged on years.year = flagged.year and rules.rule_code = flagged.rule_code
left join quarantined on years.year = quarantined.year and rules.rule_code = quarantined.rule_code
order by years.year, rules.rule_code
