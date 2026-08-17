-- dialect: 
SELECT o.id, cust_id AS customer_id, amount * (1 + tax_rate) AS total_with_tax
FROM orders o INNER JOIN customers c ON o.customer_id = c.id
