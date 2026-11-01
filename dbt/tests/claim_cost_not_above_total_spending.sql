-- No person's PMI-scope claim cost may exceed their total health spending (issue #15). Event costs
-- carry cents and TOTEXP is rounded to whole dollars, so a cost within one dollar of TOTEXP passes.
select claims.year, claims.DUPERSID, claims.claim_cost, person.TOTEXP
from {{ ref('int_person_claims') }} as claims
inner join {{ ref('int_person_clean') }} as person
    on claims.year = person.year and claims.DUPERSID = person.DUPERSID
where claims.claim_cost >= person.TOTEXP + 1
