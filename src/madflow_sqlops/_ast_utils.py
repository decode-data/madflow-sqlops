"""Small helpers shared by every category handler in _categories.py."""

from __future__ import annotations

from sqlglot import exp


def source_columns(node: exp.Expression) -> list[str]:
    """Every column name referenced anywhere in node's subtree, deduped, first-occurrence order.

    A lightweight structural signal (gdt's own scope note in docs/grammar.md -> compute) --
    not a lineage graph, no cross-model resolution.
    """
    seen: dict[str, None] = {}
    for column in node.find_all(exp.Column):
        seen.setdefault(column.name, None)
    return list(seen)


def expression_summary(node: exp.Expression, dialect: str | None) -> str:
    return node.sql(dialect=dialect)


def alias_output(node: exp.Expression) -> str | None:
    """If node is the immediate value of an Alias, return the alias name; else None."""
    parent = node.parent
    if isinstance(parent, exp.Alias) and parent.this is node:
        return parent.alias
    return None
