"""Jinja2 templates for vault markdown notes.

Templates live as strings here (not separate files) so that rendering is a
pure-function call with no filesystem dependency — makes them trivial to unit
test.
"""
from __future__ import annotations

from jinja2 import Environment, StrictUndefined

_env = Environment(
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
    undefined=StrictUndefined,
)


DATA_BRIEFING = _env.from_string(
    """\
---
type: briefing
subtype: data-ingestion
date: {{ date }}
generated_at: {{ generated_at }}
---
# Data ingestion — {{ date }}

## Summary

- **New rows inserted:** {{ report.inserted }}
- **Duplicates skipped:** {{ report.skipped }}
- **Total seen:** {{ report.total_seen }}

### Rows in DB (last 14 days, by source)
{% if counts %}
| Source | Rows |
| --- | ---: |
{% for src, n in counts.items() %}
| {{ src }} | {{ n }} |
{% endfor %}
{% else %}
_(no rows yet)_
{% endif %}

## Senate trades — new today
{% if senate_new %}
| Senator | Ticker | Side | Tx Date | Filing | Range |
| --- | --- | --- | --- | --- | --- |
{% for r in senate_new %}
| {{ r.person_name }} | {{ r.ticker }} | {{ r.transaction_type }} | {{ r.transaction_date }} | {{ r.filing_date }} | {{ r.amount_range }} |
{% endfor %}
{% else %}
_(none)_
{% endif %}

## House trades — new today
{% if house_new %}
| Rep | Ticker | Side | Tx Date | Filing | Range |
| --- | --- | --- | --- | --- | --- |
{% for r in house_new %}
| {{ r.person_name }} | {{ r.ticker }} | {{ r.transaction_type }} | {{ r.transaction_date }} | {{ r.filing_date }} | {{ r.amount_range }} |
{% endfor %}
{% else %}
_(none)_
{% endif %}

## Insider trades — new today
{% if insider_new %}
| Name | Ticker | Side | Tx Date | Filing | Est. $ |
| --- | --- | --- | --- | --- | ---: |
{% for r in insider_new %}
| {{ r.person_name }} | {{ r.ticker }} | {{ r.transaction_type }} | {{ r.transaction_date }} | {{ r.filing_date }} | {{ r.amount_range }} |
{% endfor %}
{% else %}
_(none)_
{% endif %}

## Top tickers (14d, by rows)
{% if top_tickers %}
| Ticker | Rows |
| --- | ---: |
{% for t, n in top_tickers %}
| {{ t }} | {{ n }} |
{% endfor %}
{% else %}
_(no tickers yet)_
{% endif %}
"""
)


PHASE_COMPLETE = _env.from_string(
    """\
---
type: phase-complete
phase: {{ phase }}
date: {{ date }}
---
# Phase {{ phase }} complete — {{ date }}

## What was built
{% for item in built %}
- {{ item }}
{% endfor %}

## What was tested
{% for item in tested %}
- {{ item }}
{% endfor %}

## What is deferred
{% for item in deferred %}
- {{ item }}
{% endfor %}

## Acceptance criteria
{% for c in acceptance %}
- [{{ 'x' if c.ok else ' ' }}] {{ c.text }}{% if c.note %} — {{ c.note }}{% endif %}
{% endfor %}

## Next step
{{ next_step }}
"""
)


def render_data_briefing(**kwargs: object) -> str:
    return DATA_BRIEFING.render(**kwargs)


def render_phase_complete(**kwargs: object) -> str:
    return PHASE_COMPLETE.render(**kwargs)
