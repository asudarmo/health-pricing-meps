-- One row per inpatient, hospital outpatient and office-based event for 2022 and 2023, with the
-- PMI-scope flags from the approved definition (issue #15). Read through the staging models.
-- er_originated_stay marks inpatient stays that began in the emergency room. They are out of the
-- base definition and kept as their own columns so the M5 sensitivity needs no rebuild.
with inpatient as (
    select 2022 as year, DUPERSID, EVNTIDX, 'inpatient' as event_type, IPXP22X as cost,
           {{ pmi_stay_not_birth() }} as not_birth, EMERROOM = 1 as er_originated
    from {{ ref('stg_inpatient_2022') }}
    union all
    select 2023, DUPERSID, EVNTIDX, 'inpatient', IPXP23X,
           {{ pmi_stay_not_birth() }}, EMERROOM = 1
    from {{ ref('stg_inpatient_2023') }}
),

visits as (
    select 2022 as year, DUPERSID, EVNTIDX, 'outpatient' as event_type, OPXP22X as cost,
           {{ pmi_visit_in_scope() }} as in_scope
    from {{ ref('stg_outpatient_2022') }}
    union all
    select 2023, DUPERSID, EVNTIDX, 'outpatient', OPXP23X, {{ pmi_visit_in_scope() }}
    from {{ ref('stg_outpatient_2023') }}
    union all
    select 2022, DUPERSID, EVNTIDX, 'office_based', OBXP22X, {{ pmi_visit_in_scope() }}
    from {{ ref('stg_office_based_2022') }}
    union all
    select 2023, DUPERSID, EVNTIDX, 'office_based', OBXP23X, {{ pmi_visit_in_scope() }}
    from {{ ref('stg_office_based_2023') }}
)

select
    year, DUPERSID, EVNTIDX, event_type, cost,
    not_birth and not er_originated as in_scope,
    not_birth and er_originated as er_stay
from inpatient
union all
select
    year, DUPERSID, EVNTIDX, event_type, cost,
    coalesce(in_scope, false) as in_scope,
    false as er_stay
from visits
