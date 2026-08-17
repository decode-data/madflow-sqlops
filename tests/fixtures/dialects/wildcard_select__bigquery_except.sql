-- dialect: bigquery
SELECT * EXCEPT (internal_id, updated_at) FROM orders
