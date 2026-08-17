-- dialect: snowflake
SELECT ticket_id, AI_COMPLETE('llama3-8b', prompt_text) AS response FROM support_tickets
