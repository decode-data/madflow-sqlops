-- dialect: 
SELECT o.id, c.name FROM orders o INNER JOIN customers c ON o.customer_id = c.id
