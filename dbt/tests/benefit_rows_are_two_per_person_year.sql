-- Every person-year in mart_person_year has exactly one row for each benefit type, and the benefit
-- table has no person-year that is not in the mart (issue #24). Returns the offending person-years.
with counted as (
    select year, DUPERSID, count(*) as row_count, count(distinct benefit_type) as benefit_types
    from {{ ref('mart_person_year_benefit') }}
    group by year, DUPERSID
)

select mart.year, mart.DUPERSID, counted.row_count, counted.benefit_types
from {{ ref('mart_person_year') }} as mart
full join counted
    on mart.year = counted.year and mart.DUPERSID = counted.DUPERSID
where mart.DUPERSID is null
    or counted.DUPERSID is null
    or counted.row_count <> 2
    or counted.benefit_types <> 2
