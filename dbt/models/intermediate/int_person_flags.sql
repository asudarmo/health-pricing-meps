-- One row per person-year with a flag for each exclusion rule (issue #14). A rule is a reason a
-- person-year is not in the modelling population. quarantine_person and exclusion_log read this.
select
    person.year,
    person.DUPERSID,
    person.DUID,
    person.perwt,
    person.TOTEXP,
    exposure.exposure,
    row_number() over (partition by person.year, person.DUPERSID order by person.DUID) > 1
        as duplicate_person_year,
    exposure.exposure is null or exposure.exposure = 0 as no_exposure,
    person.age is null or person.SEX is null or person.region is null or person.inscov is null
        as missing_core_factor,
    person.TOTEXP < 0 or person.TOTSLF < 0 or person.TOTMCR < 0 or person.TOTMCD < 0
        or person.TOTPRV < 0 or person.TOTPTR < 0 as negative_expenditure,
    -- Modelling population definition (decision gate 3, approved 2026-11-01). Persons with a zero
    -- person weight are outside the surveyed population or did not respond fully.
    person.perwt = 0 as not_in_analytic_population
from {{ ref('int_person_clean') }} as person
inner join {{ ref('int_person_exposure') }} as exposure
    on person.year = exposure.year and person.DUPERSID = exposure.DUPERSID
