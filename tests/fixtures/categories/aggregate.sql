-- dialect: 
SELECT customer_id, SUM(amount) AS total_spent, COUNT(DISTINCT order_id) AS order_count FROM orders GROUP BY customer_id
