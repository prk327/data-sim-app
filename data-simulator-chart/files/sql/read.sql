Select {{columns}}
	FROM (SELECT {{columns}}, count(*), ROW_NUMBER() OVER (ORDER BY {{columns}}) as rowid
FROM {{schema}}.{{table_name}} group by {{columns}} order by {{columns}}) U
{% if condition %} WHERE {{ condition }}{% endif %} limit {{limit}}