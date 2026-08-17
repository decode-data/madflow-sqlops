-- dialect: 
SELECT customer_id, SHA2(email, 256) AS email_hash FROM customers
