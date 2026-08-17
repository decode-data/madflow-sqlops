-- dialect: snowflake
SELECT * EXCLUDE (internal_id, updated_at) FROM orders
