---
name: madflow-sqlops
description: Use this skill when working with SQL operation classification, GDT (Grammar of Data Transformation) tagged output, or the madflow-sqlops package specifically -- parsing a SQL query and classifying its transformation operations (joins, renames, computed columns, casts, aggregates, window functions, JSON extraction, AI/UDF/hash function calls, ...) against the GDT taxonomy. Trigger on "GDT", "tag_operations", "madflow-sqlops", "classify this SQL", "what operations does this query do".
---

# madflow-sqlops

Reference implementation of [GDT](https://github.com/decode-data/gdt) (Grammar of Data Transformation): parses SQL via `sqlglot`, walks the AST once, and emits a structured, dialect-agnostic classification of every transformation operation in the query. Pinned to GDT `v0.2.0` (`gdt_version` "0.2") -- see `src/madflow_sqlops/_version.py` for the constants.

Library and CLI only -- no lineage tracking, no rule evaluation, no ruleset YAML, no app-specific types. See the repo README's Non-goals section before reaching for this package to do more than tag operations.

## Invocation

CLI (GDT JSON to stdout):

```
madflow-sqlops tag file.sql --dialect snowflake            # compact JSON
madflow-sqlops tag file.sql --dialect snowflake --pretty    # indented
echo "SELECT ..." | madflow-sqlops tag - --dialect duckdb   # stdin
```

Python API, for in-process use:

```python
from madflow_sqlops import tag_operations

result = tag_operations(sql, dialect="snowflake")
result.gdt_version        # "0.2"
result.operations.join    # [...]
result.operations.rename  # [...]
result.cache_key          # sha256 hex string, hash of (dialect, sql) -- persistence is the caller's concern
result.to_dict()          # raw dict, already validated against the GDT schema
```

`dialect` is required on both paths -- there's no default. Every one of the 17 current GDT categories is always present as a key in `operations` (an empty list if the query has no occurrences of that category), so `result.operations.<category>` is always safe to access.

## Output shape

Don't rely on this doc for the exact field shapes -- read the schema. The authoritative JSON Schema is vendored at `src/madflow_sqlops/_schema/gdt-v0.1.schema.json` (filename intentionally still says "v0.1"; its content is the pinned v0.2 schema -- see `_schema_validation.py`'s comment). For the human-readable category reference with worked examples, read `../gdt/docs/grammar.md` and `../gdt/docs/categories.md` in the sibling `gdt` repo if it's checked out alongside this one, or the same paths at the pinned tag on GitHub otherwise.

## Gotchas

- **Dialect is never defaulted.** Passing the wrong dialect (or omitting it, which is a hard error, not a fallback) can silently change which category a construct lands in -- e.g. a `CASE` vs. an unrecognized dialect function.
- **A cache hit is structurally identical to a fresh tag.** `tag_operations()` doesn't do its own caching -- it exposes `cache_key` so a caller can build one -- and there's no field on the result marking "this came from cache." If you're debugging a caching layer built on top of this package, don't expect a signal here; check the caller's cache, not the tagged output.
- **Output shape can lag the latest GDT spec.** This package pins one GDT version (currently `v0.2.0`); if `gdt` has released a newer tag with additional categories or fields, they won't appear in `tag_operations()`'s output until this package bumps its pin (see `CONTRIBUTING.md` -> GDT version changes).
- **`ai_function` and `udf` are name-based, not AST-based**, and the `ai_function` allowlist (`src/madflow_sqlops/_allowlists.py`) is deliberately incomplete -- GDT itself doesn't enumerate vendor function names. A real AI/ML function call not yet in the allowlist is tagged `udf`, not silently dropped, but it's a known source of false negatives, not a bug to chase per-query.
