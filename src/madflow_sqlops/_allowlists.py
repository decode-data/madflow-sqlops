"""Name-based allowlists for the categories gdt grounds in function names rather
than a dedicated sqlglot AST node (docs/decisions.md, 0003).

Both lists are deliberately partial. gdt does not enumerate vendor function
names anywhere in the spec (ADR 0003's own reasoning: the list churns faster
than any spec's release cadence), so this is a starter set seeded from the
examples in ../gdt/docs/grammar.md, not a claim of completeness. Expect real
false negatives for functions not yet listed here -- that's the documented,
expected failure mode of name-based detection, not a bug.

Matching is against the *unqualified* function name, lowercased (the part
after any "namespace." prefix stripped by a Dot-wrapped call such as
`ML.GENERATE_TEXT` or `my_schema.normalize_phone`).
"""

from __future__ import annotations

AI_FUNCTION_NAMES: frozenset[str] = frozenset(
    {
        # Snowflake Cortex
        "ai_complete",
        "ai_classify",
        "ai_summarize_agg",
        "ai_filter",
        "ai_similarity",
        "ai_sentiment",
        "ai_extract",
        # BigQuery ML.* / AI.*
        "generate_text",
        "generate",
        "generate_embedding",
        "forecast",
        # Databricks
        "ai_query",
        "ai_generate_text",
        "ai_summarize",
    }
)

# Dialect-specific hash functions sqlglot has no dedicated AST node for, so they
# parse as exp.Anonymous. exp.MD5 / exp.SHA / exp.SHA2 (and, as of the pinned
# sqlglot version, exp.FarmFingerprint) are handled separately via their own
# dedicated node types -- this list is only the true name-based fallback.
COLUMN_HASH_FALLBACK_NAMES: frozenset[str] = frozenset(
    {
        "hash",  # Snowflake generic HASH()
        "farm_fingerprint",
        "farmfingerprint64",
    }
)
