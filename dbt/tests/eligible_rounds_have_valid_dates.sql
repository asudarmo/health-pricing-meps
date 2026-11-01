-- Exposure (int_person_exposure) counts months only inside a round's reference period, so an
-- eligible round with a missing or reserved date would silently lower the exposure.
{% for rnd in [31, 42, 53] %}
select year, DUPERSID, {{ rnd }} as round
from {{ ref('int_person_clean') }}
where ELGRND{{ rnd }} = 1
    and (BEGRFM{{ rnd }} is null or BEGRFY{{ rnd }} is null or ENDRFM{{ rnd }} is null
         or ENDRFY{{ rnd }} is null or BEGRFM{{ rnd }} < 1 or ENDRFM{{ rnd }} < 1)
{{ "union all" if not loop.last }}
{% endfor %}
