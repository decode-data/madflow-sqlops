-- dialect: bigquery
SELECT JSON_VALUE(payload, '$.email') AS user_email FROM events
