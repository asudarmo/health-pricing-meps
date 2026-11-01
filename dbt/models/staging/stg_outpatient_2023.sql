-- Passthrough for M1. PMI-scope filtering (decision gate 2) lands in M2 (plan.md section 5).
select * from {{ source('raw', 'outpatient_2023') }}
