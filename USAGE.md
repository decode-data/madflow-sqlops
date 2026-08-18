# Using madflow-sqlops

Practical guide to installing and running `tag_operations()`/the CLI against real SQL. For architecture, the public API's design rationale, and the gdt spec itself, see [README.md](README.md). This doc is task-oriented: "how do I actually run this."

Not yet published to PyPI — install from the git repo (see below). Pinned to `v0.1.0` throughout this doc; move the pin forward as new tags land.

## Install

Not on PyPI yet, so install directly from the repo, pinned to a tag rather than tracking `main` (which will keep moving):

```bash
pip install "git+https://github.com/decode-data/madflow-sqlops@v0.1.0"
# or, with uv:
uv pip install "git+https://github.com/decode-data/madflow-sqlops@v0.1.0"
```

Verified against a clean install with no source checkout — both the library import and the `madflow-sqlops` CLI command work directly after this.

To add it as a pinned dependency in another project's `pyproject.toml`:

```toml
dependencies = [
    "madflow-sqlops @ git+https://github.com/decode-data/madflow-sqlops@v0.1.0",
]
```

When a new tag lands (bug fixes, new categories), bump the `@v0.1.0` pin — that's the whole update, no other coordination needed.

## Quick start — CLI

```bash
madflow-sqlops tag path/to/model.sql --dialect snowflake            # compact JSON to stdout
madflow-sqlops tag path/to/model.sql --dialect snowflake --pretty    # indented, human-readable
echo "SELECT * FROM raw.orders" | madflow-sqlops tag - --dialect snowflake   # stdin
```

`--dialect` is always required — there's no default, because dialect changes how specific syntax gets classified (e.g. Snowflake `IFF(...)` vs. BigQuery `IF(...)` both normalize to the same `conditional` shape, but only if the right dialect is given). Use `""` explicitly if you genuinely want generic/ANSI parsing with no dialect-specific handling:

```bash
madflow-sqlops tag model.sql --dialect ""
```

## Quick start — Python API

```python
from madflow_sqlops import tag_operations

result = tag_operations(sql, dialect="snowflake")
result.gdt_version          # "0.2"
result.operations.join      # [...]
result.operations.rename    # [...]
result.operations.aggregate # [...]  -- one entry per aggregate function call
result.cache_key             # sha256 hex string, hash of (dialect, sql) -- your own caching is on you
result.to_dict()             # the full raw dict, already schema-validated
```

Every one of the 17 gdt categories is always present as a key on `result.operations` — an empty list if that query has none, never a missing attribute. Full category reference: [gdt's docs/categories.md](https://github.com/decode-data/gdt/blob/v0.2.0/docs/categories.md).

## Tagging a whole directory (e.g. a data mart's raw/staging models)

### Shell, via the CLI

```bash
mkdir -p tagged
for f in models/**/*.sql; do
  name=$(basename "$f" .sql)
  madflow-sqlops tag "$f" --dialect snowflake > "tagged/${name}.json" \
    || echo "FAILED: $f" >> tagged/_failures.log
done
```

### Python, for a combined report

```python
from pathlib import Path
import json
from madflow_sqlops import tag_operations

results = {}
failures = {}
for sql_file in Path("models").rglob("*.sql"):
    sql = sql_file.read_text()
    try:
        results[str(sql_file)] = tag_operations(sql, dialect="snowflake").to_dict()
    except Exception as e:
        failures[str(sql_file)] = f"{type(e).__name__}: {e}"

Path("tagged.json").write_text(json.dumps(results, indent=2))
if failures:
    print(f"{len(failures)} file(s) failed to tag:")
    for f, err in failures.items():
        print(f"  {f}: {err}")
```

Catch broadly (`Exception`) when batch-processing a whole directory unattended — see Known limitations below for what actually trips this, and prefer narrowing the `except` once you've seen what your own corpus actually throws.

## Choosing `--dialect` / `dialect=`

Must match how the SQL was actually written. Common values: `snowflake`, `bigquery`, `duckdb`, `postgres`, `redshift`, `databricks`, `spark`, `mysql`, `tsql` (SQL Server), `hive`. Full list is whatever `sqlglot` supports (this package doesn't maintain its own list). `""` means "generic/ANSI, no dialect-specific normalization" — fine for portable SQL, but Snowflake/BigQuery-specific syntax (e.g. `IFF`, `QUALIFY`, backtick-quoted identifiers) won't parse correctly under it.

## Reading the output

Top level:

```json
{
  "gdt_version": "0.2",
  "operations": { "join": [...], "filter": [...], "compute": [...], "...": "..." }
}
```

Every category's entries are independent and can overlap on the same underlying SQL construct by design — e.g. `SUM(x) AS total` produces both an `aggregate` entry (it's a sum) and a `compute` entry (the column `total` is derived, not a passthrough). Don't expect a category's entries to be mutually exclusive with another category's.

`join`/`aggregate`/etc. entries are **flat per query** — nothing in the current output says which CTE a given join or computed column came from (tracked as a possible future spec extension: [gdt#13](https://github.com/decode-data/gdt/issues/13) / [madflow-sqlops#12](https://github.com/decode-data/madflow-sqlops/issues/12), not implemented). If you need per-CTE structural checks today, `subquery_cte` entries already carry `kind` (`cte`/`subquery`), `alias`, and `location` — enough for "no inline subqueries," "no subqueries in WHERE," and CTE-naming-convention checks without waiting on that.

## Known limitations, worth knowing before Monday

- **dbt `.sql` model files are Jinja-templated, not plain SQL** (`{{ ref('orders') }}`, `{{ config(...) }}`, macro calls) — `tag_operations()` parses SQL, not Jinja, and will raise a `sqlglot` parse error on a raw, un-rendered dbt model file. Feed it *compiled* SQL (dbt's `target/compiled/.../model.sql` output after `dbt compile`, or `target/run/` after a real run), not the source model file, if your raw data mart is dbt-managed. Tested this gap directly against real dbt packages (Fivetran's `dbt_stripe`/`dbt_shopify`) — plain hand-written SQL views/queries don't have this problem at all.
- **One SQL statement per call.** A file with multiple semicolon-separated statements (`CREATE TABLE ...; INSERT INTO ...;`) raises `ValueError` rather than silently tagging only one or merging both — split multi-statement files before tagging, one `tag_operations()` call per statement.
- **Extremely deep nesting can hit Python's recursion limit** (`sqlglot`'s own parser, not this package's code) — realistically this means hundreds of levels of nested parens/`CASE`/joins, not normal hand-written or dbt-compiled SQL. The CLI reports this as a clean `madflow-sqlops: maximum recursion depth exceeded while calling a Python object` message rather than a raw traceback; the library raises `RecursionError` uncaught.
- **`ai_function`/`udf` name-matching is a maintained allowlist, not exhaustive** — a real AI/ML function call not yet in `src/madflow_sqlops/_allowlists.py` gets tagged `udf` instead, not silently dropped, but won't show up as `ai_function` until the allowlist is updated. Low-relevance for a raw data mart layer, more relevant further downstream.
- **Output validates against gdt schema `0.2` specifically** (pinned in `src/madflow_sqlops/_version.py`) — if `gdt` releases a newer schema version upstream, this package's output won't include any new categories/fields until its own pin is bumped.

## Found a bug?

Paste the error and the SQL (or a minimal reproduction) into a Claude Code session against this repo — that's been the fastest loop so far (branch → fix → regression test → PR → your merge approval). No formal bug-report process yet; see [decode-data/madflow-sqlops CONTRIBUTING.md](CONTRIBUTING.md) if that changes.
