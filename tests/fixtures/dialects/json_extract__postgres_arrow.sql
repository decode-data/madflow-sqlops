-- dialect: postgres
SELECT payload ->> 'email' AS user_email FROM events
