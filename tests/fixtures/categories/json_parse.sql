-- dialect: snowflake
SELECT PARSE_JSON(raw_payload) AS payload FROM events
