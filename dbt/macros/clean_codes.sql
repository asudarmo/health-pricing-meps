{#
  Reserved-code treatment for int_person_clean (issue #12). The rules are logged in
  _docs/decisions.md. MEPS reserved codes are -1 inapplicable, -7 refused, -8 don't know and
  -15 cannot be computed.
#}

{# Reserved codes become null. Pass a narrower list when a code is meaningful, e.g. -1 on round dates. #}
{% macro null_reserved(col, codes='-15, -8, -7, -1') %}
    case when {{ col }} in ({{ codes }}) then null else {{ col }} end
{% endmacro %}

{#
  A yes/no question. 1 becomes '1' and 2 becomes '0'. For -1 the rule depends on the question.
  Adult-only questions (age_restricted): -1 for a child is 'not_applicable' and -1 for an adult is
  'unknown'. Questions asked at any age: -1 is 'unknown'. -7, -8 and -15 become null.
#}
{% macro yes_no_level(col, age_restricted=false) %}
    case
        when {{ col }} = -1 and {{ age_restricted }} and age < 18 then 'not_applicable'
        when {{ col }} = -1 then 'unknown'
        when {{ col }} in (-15, -8, -7) then null
        when {{ col }} = 1 then '1'
        when {{ col }} = 2 then '0'
    end
{% endmacro %}

{# The same rule for a question with more than two answers, which keep their codes as text. #}
{% macro category_level(col, age_restricted=false) %}
    case
        when {{ col }} = -1 and {{ age_restricted }} and age < 18 then 'not_applicable'
        when {{ col }} = -1 then 'unknown'
        when {{ col }} in (-15, -8, -7) then null
        else cast({{ col }} as varchar)
    end
{% endmacro %}

{# The latest round with a valid answer (1 to 5), 5/3 first. #}
{% macro latest_round(stem) %}
    coalesce(
        case when {{ stem }}53 between 1 and 5 then {{ stem }}53 end,
        case when {{ stem }}42 between 1 and 5 then {{ stem }}42 end,
        case when {{ stem }}31 between 1 and 5 then {{ stem }}31 end
    )
{% endmacro %}

{% macro latest_round_source(stem) %}
    case
        when {{ stem }}53 between 1 and 5 then 53
        when {{ stem }}42 between 1 and 5 then 42
        when {{ stem }}31 between 1 and 5 then 31
    end
{% endmacro %}
