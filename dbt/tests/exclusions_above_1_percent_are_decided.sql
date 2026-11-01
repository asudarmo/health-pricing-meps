-- Gate 3 (AGENTS.md). A rule that removes more than 1% of persons or of cost must have the user's
-- decision recorded in exclusion_log, otherwise this test fails.
select year, rule_code, share_of_persons, share_of_totexp
from {{ ref('exclusion_log') }}
where gate3_decision = 'needs user decision'
