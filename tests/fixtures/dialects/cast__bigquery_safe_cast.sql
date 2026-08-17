-- dialect: bigquery
SELECT SAFE_CAST(raw_value AS NUMERIC) AS parsed_value FROM staging
