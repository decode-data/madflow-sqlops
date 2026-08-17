-- dialect: snowflake
SELECT TRY_CAST(raw_value AS NUMBER) AS parsed_value FROM staging
