-- dialect: bigquery
SELECT o.order_id, tag FROM orders o, UNNEST(o.tags) AS tag
