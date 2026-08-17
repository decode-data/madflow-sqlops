-- dialect: bigquery
SELECT IF(status = 'active', 1, 0) AS is_active FROM users
