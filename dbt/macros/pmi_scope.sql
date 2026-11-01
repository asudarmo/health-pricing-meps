{#
  The approved PMI-scope claim definition (decision gate 2, _docs/decisions.md, 2026-11-01).
  src/health_pricing/evidence/pmi_scope.py holds the same rules for the evidence tables, and
  tests/test_claims.py checks that the two agree on the real data.
#}

{# Hospital outpatient and office-based events share one rule. #}
{% macro pmi_visit_in_scope() %}
    (
        (DRSPLTY_M18 > 0 and DRSPLTY_M18 not in (6, 8, 14, 24))
        or (DRSPLTY_M18 = -1 and MEDPTYPE_M18 in (10, 13, 15))
    )
    and VSTCTGRY not in (1, 6, 7, 8, 9, 10)
{% endmacro %}

{# Birth and pregnancy stays are out of every inpatient claim. #}
{% macro pmi_stay_not_birth() %}
    RSNINHOS not in (4, 5, 6)
{% endmacro %}
