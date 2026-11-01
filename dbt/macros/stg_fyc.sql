{#
  Shared column list for the Full-Year Consolidated staging models, so 2022 and 2023 expose the
  same names. Variables whose name carries the survey year (AGE22X, TOTEXP23, ...) are renamed
  to the year-neutral name. Variables with the same name in both years, and the round-pair
  variables (suffix 31, 42, 53), keep AHRQ's name. The list is the shortlist approved at decision
  gate 1 (_docs/variable-mapping.md). BMI and ADSMOK42 are left out because they are not
  available in both years. Values are not changed here, see int_person_clean.
#}
{% macro stg_fyc_columns(yy, year) %}
    {{ year }} as year,
    DUID,
    PID,
    DUPERSID,
    PANEL,
    VARSTR,
    VARPSU,
    FAMID{{ yy }} as famid,
    PERWT{{ yy }}F as perwt,
    AGE{{ yy }}X as age,
    AGELAST,
    SEX,
    REGION{{ yy }} as region,
    REGION31,
    REGION42,
    REGION53,
    INSCOV{{ yy }} as inscov,
    {% for stem in ['RTHLTH', 'MNHLTH', 'BEGRFM', 'BEGRFY', 'ENDRFM', 'ENDRFY', 'ELGRND'] %}
    {% for rnd in [31, 42, 53] %}
    {{ stem }}{{ rnd }},
    {% endfor %}
    {% endfor %}
    ENDRFM{{ yy }} as ENDRFM,
    ENDRFY{{ yy }} as ENDRFY,
    ELGRND{{ yy }} as ELGRND,
    OFTSMK53,
    PHYEXE53,
    HIBPDX,
    CHDDX,
    ANGIDX,
    MIDX,
    OHRTDX,
    STRKDX,
    CHOLDX,
    CANCERDX,
    ARTHDX,
    ASTHDX,
    ASSTIL31,
    DIABDX_M18,
    {% for stem in ['OBTOTV', 'OPTOTV', 'ERTOT', 'IPDIS', 'IPNGTD', 'RXTOT', 'OBDRV'] %}
    {{ stem }}{{ yy }} as {{ stem }},
    {% endfor %}
    {% for stem in ['TOTEXP', 'TOTSLF', 'TOTMCR', 'TOTMCD', 'TOTPRV', 'TOTPTR', 'OBVEXP', 'OBDEXP', 'OPTEXP', 'ERTEXP', 'IPTEXP', 'RXEXP'] %}
    {{ stem }}{{ yy }} as {{ stem }}{{ "," if not loop.last }}
    {% endfor %}
{% endmacro %}
