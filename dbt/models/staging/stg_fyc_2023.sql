-- Year-neutral names for the shortlisted variables. Values are unchanged (see stg_fyc_columns).
select{{ stg_fyc_columns('23', 2023) }}
from {{ source('raw', 'fyc_2023') }}
