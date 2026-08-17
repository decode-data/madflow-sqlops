-- dialect: snowflake
SELECT payload:email::string AS user_email FROM events
