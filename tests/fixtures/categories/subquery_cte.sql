-- dialect: 
WITH recent_orders AS (SELECT * FROM orders WHERE order_date > '2026-01-01') SELECT customer_id, COUNT(*) AS order_count FROM recent_orders GROUP BY customer_id
