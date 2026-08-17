"""tag_operations() -- see README -> Architecture and Public API sketch."""

from __future__ import annotations

import sqlglot

from ._cache import cache_key as _cache_key
from ._categories import build_operations
from ._result import Operations, TaggedResult
from ._schema_validation import validate
from ._version import GDT_SCHEMA_VERSION


def tag_operations(sql: str, dialect: str) -> TaggedResult:
    """Parse `sql` under `dialect`, classify every gdt category, validate, return.

    `dialect` is required and never defaulted -- README -> Architecture: "Dialect
    matters; don't assume a default."
    """
    root = sqlglot.parse_one(sql, dialect=dialect)
    ops_dict = build_operations(root, dialect)

    document = {"gdt_version": GDT_SCHEMA_VERSION, "operations": ops_dict}
    validate(document)

    return TaggedResult(
        gdt_version=GDT_SCHEMA_VERSION,
        operations=Operations.from_dict(ops_dict),
        cache_key=_cache_key(sql, dialect),
    )
