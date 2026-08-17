"""Cross-dialect normalization -- see tests/fixtures/dialects/ and
../gdt/docs/decisions.md (0001).

Each group's variants use genuinely different SQL syntax (Snowflake IFF vs.
ANSI CASE, Postgres -> vs. BigQuery JSON_VALUE, ...) that must all normalize
to the identical entry for that one category -- only that category's slice
of the output is compared, since other categories (e.g. `compute`'s
expression_summary) legitimately differ across dialects by design.
"""

from __future__ import annotations

from madflow_sqlops import tag_operations


def test_dialect_variant_matches_shared_expected_entries(dialect_variant):
    result = tag_operations(dialect_variant.sql, dialect=dialect_variant.dialect)
    actual = getattr(result.operations, dialect_variant.category)
    assert actual == dialect_variant.expected_entries


def test_every_group_has_at_least_two_variants():
    from .conftest import discover_dialect_variants

    variants = discover_dialect_variants()
    groups: dict[str, int] = {}
    for v in variants:
        groups[v.group] = groups.get(v.group, 0) + 1
    thin = {g: n for g, n in groups.items() if n < 2}
    assert not thin, f"cross-dialect groups with fewer than 2 variants: {thin}"
