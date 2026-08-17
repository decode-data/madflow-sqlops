-- dialect: snowflake
SELECT IFF(status = 'active', 1, 0) AS is_active FROM users
