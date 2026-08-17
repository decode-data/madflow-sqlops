"""Coarse regression net: more realistic, multi-feature SQL than the
single-purpose category/combination fixtures.

Not golden-file matched -- these don't assert an exact expected shape, only
that tagging a query this size doesn't crash and that the result validates
against the vendored GDT schema. The category/combination fixtures already
cover exact-shape correctness per category in isolation; this file exists to
catch interactions between categories that only show up at realistic query
complexity (multiple CTEs, multiple joins, nested subqueries, mixed
categories in one query) which the single-purpose fixtures don't exercise.
"""

from __future__ import annotations

import pytest

from madflow_sqlops import tag_operations
from madflow_sqlops._schema_validation import validate

CORPUS: list[tuple[str, str, str]] = [
    (
        "multi_cte_multi_join",
        "",
        """
        WITH recent_orders AS (
            SELECT * FROM orders WHERE order_date > '2026-01-01'
        ), customer_totals AS (
            SELECT customer_id, SUM(amount) AS total_spent
            FROM recent_orders
            GROUP BY customer_id
        )
        SELECT c.name, ct.total_spent, o.status
        FROM customer_totals ct
        JOIN customers c ON ct.customer_id = c.id
        LEFT JOIN orders o ON o.customer_id = c.id
        WHERE ct.total_spent > 100
        """,
    ),
    (
        "nested_subqueries_and_wildcard",
        "",
        """
        SELECT t.*, ranked.rnk
        FROM (SELECT * FROM orders WHERE status = 'completed') t
        JOIN (
            SELECT order_id, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date) AS rnk
            FROM orders
        ) ranked ON t.id = ranked.order_id
        """,
    ),
    (
        "mixed_json_and_hash_and_cast",
        "snowflake",
        """
        SELECT
            customer_id,
            payload:email::string AS email,
            SHA2(payload:email::string, 256) AS email_hash,
            TRY_CAST(payload:age AS NUMBER) AS age,
            CASE WHEN payload:vip::boolean THEN 'vip' ELSE 'standard' END AS tier
        FROM events
        """,
    ),
    (
        "ai_and_udf_and_aggregate_together",
        "snowflake",
        """
        SELECT
            ticket_id,
            AI_CLASSIFY(prompt_text, ['billing', 'technical']) AS category,
            my_schema.normalize_phone(phone_number) AS phone,
            COUNT(*) AS ticket_count
        FROM support_tickets
        GROUP BY ticket_id, prompt_text, phone_number
        """,
    ),
    (
        "deep_set_op_and_unnest",
        "bigquery",
        """
        SELECT id FROM a
        UNION ALL
        SELECT id FROM b
        UNION ALL
        SELECT o.order_id AS id FROM orders o, UNNEST(o.tags) AS tag
        """,
    ),
]


@pytest.mark.parametrize("name,dialect,sql", CORPUS, ids=[c[0] for c in CORPUS])
def test_corpus_query_tags_without_crashing_and_validates(name, dialect, sql):
    result = tag_operations(sql, dialect=dialect)
    validate(result.to_dict())
