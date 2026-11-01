-- The modelling population: person-years that no exclusion rule holds out (issue #14).
-- If a person-year appears twice, the first copy stays and the later copies are in quarantine.
with numbered as (
    select
        person.*,
        exposure.exposure_months,
        exposure.exposure,
        row_number() over (partition by person.year, person.DUPERSID order by person.DUID)
            as copy_number
    from {{ ref('int_person_clean') }} as person
    inner join {{ ref('int_person_exposure') }} as exposure
        on person.year = exposure.year and person.DUPERSID = exposure.DUPERSID
)

select * exclude (copy_number)
from numbered
where copy_number = 1
    and not exists (
        select 1
        from {{ ref('quarantine_person') }} as held
        where held.year = numbered.year
            and held.DUPERSID = numbered.DUPERSID
            and held.reason_code <> 'duplicate_person_year'
    )
