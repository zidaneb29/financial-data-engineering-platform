{% macro field(column, path) -%}
    {%- if target.type == 'duckdb' -%}
        json_extract_string({{ column }}, '$.{{ path }}')
    {%- else -%}
        iff(is_null_value(get_path(parse_json({{ column }}), '{{ path }}')), null, get_path(parse_json({{ column }}), '{{ path }}')::varchar)
    {%- endif -%}
{%- endmacro %}

{% macro timestamp_type() -%}
    {{ 'timestamptz' if target.type == 'duckdb' else 'timestamp_tz' }}
{%- endmacro %}

{% macro observed_cutoff(column) -%}
    {%- set cutoff = var('observed_through_utc', none) -%}
    {%- if cutoff is none -%}
        true
    {%- else -%}
        {%- set utc = modules.datetime.datetime.strptime(cutoff, '%Y-%m-%dT%H:%M:%SZ') -%}
        {{ column }} <= cast('{{ utc.isoformat() }}+00:00' as {{ timestamp_type() }})
    {%- endif -%}
{%- endmacro %}

{% macro date_cutoff(column, variable) -%}
    {%- set cutoff = var(variable, none) -%}
    {%- if cutoff is none -%}
        true
    {%- else -%}
        {{ column }} <= cast('{{ modules.datetime.datetime.strptime(cutoff, "%Y-%m-%d").date().isoformat() }}' as date)
    {%- endif -%}
{%- endmacro %}

