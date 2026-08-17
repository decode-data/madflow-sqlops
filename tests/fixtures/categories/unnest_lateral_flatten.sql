-- dialect: snowflake
SELECT o.order_id, f.value AS tag FROM orders o, LATERAL FLATTEN(input => o.tags) f
