"""tag_operations() -- see README -> Architecture and Public API sketch."""

from __future__ import annotations

import sqlglot
import sqlglot.errors

from ._cache import cache_key as _cache_key
from ._categories import build_operations
from ._result import Operations, TaggedResult
from ._schema_validation import validate
from ._version import GDT_SCHEMA_VERSION


def tag_operations(sql: str, dialect: str) -> TaggedResult:
    """Parse `sql` under `dialect`, classify every gdt category, validate, return.

    `dialect` is required and never defaulted -- README -> Architecture: "Dialect
    matters; don't assume a default." `""` is accepted as a deliberate choice
    of sqlglot's generic/ANSI-ish base dialect (used throughout this package's
    own test suite for dialect-agnostic fixtures) -- there's no *implicit*
    fallback since the parameter has no default value, so an explicit blank
    string is a caller's real choice, not this function silently defaulting.
    (The CLI rejects a blank `--dialect` as a likely-accidental empty flag
    value -- that's a CLI usability concern, not a library-level one.)
    """
    root = _parse_single_statement(sql, dialect)
    ops_dict = build_operations(root, dialect)

    document = {"gdt_version": GDT_SCHEMA_VERSION, "operations": ops_dict}
    validate(document)

    return TaggedResult(
        gdt_version=GDT_SCHEMA_VERSION,
        operations=Operations.from_dict(ops_dict),
        cache_key=_cache_key(sql, dialect),
    )


def _parse_single_statement(sql: str, dialect: str) -> sqlglot.exp.Expression:
    """`sqlglot.parse_one` silently wraps multiple semicolon-separated
    statements in one `exp.Block` and returns it without complaint --
    `build_operations()` would then walk every statement's nodes and merge
    their operations into one undifferentiated, misleading result. Using
    `sqlglot.parse()` (which returns one entry per statement, `None` for a
    blank one between stray semicolons) lets that be detected and rejected
    instead of silently mistagged.
    """
    statements = [s for s in sqlglot.parse(sql, dialect=dialect) if s is not None]
    if not statements:
        raise sqlglot.errors.ParseError(f"No expression was parsed from {sql!r}")
    if len(statements) > 1:
        raise ValueError(
            f"tag_operations() tags exactly one SQL statement at a time; "
            f"found {len(statements)} statements. Split multi-statement SQL "
            "and call tag_operations() once per statement."
        )
    return statements[0]
