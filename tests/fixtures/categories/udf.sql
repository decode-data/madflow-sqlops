-- dialect: snowflake
SELECT customer_id, my_schema.normalize_phone(phone_number) AS phone FROM customers
