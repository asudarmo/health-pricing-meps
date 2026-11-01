-- On-level factor from 2022 to 2023 prices (issue #16), PCE-Health (decision gate 4, confirmed
-- 2026-11-01). The index is the committed BEA download in data/reference/ (checksum in
-- pce_health.meta.json, tests/test_price_index.py checks it). dbt runs from the repository root.
with index_values as (
    select year, index_value
    from read_csv('data/reference/pce_health.csv', header = true)
)

select
    2022 as from_year,
    2023 as to_year,
    max(index_value) filter (where year = 2022) as index_2022,
    max(index_value) filter (where year = 2023) as index_2023,
    max(index_value) filter (where year = 2023)
        / max(index_value) filter (where year = 2022) as factor
from index_values
