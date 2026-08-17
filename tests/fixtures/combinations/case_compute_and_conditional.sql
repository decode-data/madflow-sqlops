-- dialect: 
SELECT CASE WHEN status = 'active' THEN 1 ELSE 0 END AS is_active FROM users
