{#
  Household-grouped train and test split within 2022 (issue #18). There is no random state. A household
  is assigned by the first 8 hex digits of md5(DUID || salt), taken modulo 100, so the assignment is
  the same on every run and every machine. A value below 80 is train, otherwise test. The same rule
  is written in Python in tests/test_split.py, which checks the two agree.
#}
{% macro household_split(duid, salt='split-v1', train_percent=80) %}
    case
        when cast(('0x' || substr(md5(cast({{ duid }} as varchar) || '|{{ salt }}'), 1, 8)) as bigint) % 100
            < {{ train_percent }}
            then 'train'
        else 'test'
    end
{% endmacro %}
