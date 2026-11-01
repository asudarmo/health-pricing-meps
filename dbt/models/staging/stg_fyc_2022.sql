-- Passthrough for M1. Renaming, typing and validation land in M2 (plan.md section 5).
select * from {{ source('raw', 'fyc_2022') }}
