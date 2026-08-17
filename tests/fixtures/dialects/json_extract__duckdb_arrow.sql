-- dialect: duckdb
SELECT payload ->> 'email' AS user_email FROM events
