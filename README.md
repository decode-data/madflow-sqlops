# madflow-sqlops — gdt Reference Implementation

**Just want to install and run it?** See [USAGE.md](USAGE.md) — this README covers architecture and design rationale.

**License:** MIT — matches `sqlglot` exactly (this package extends it directly; matching removes any license-compatibility friction for the existing `sqlglot` community).
**Depends on:** [gdt](https://github.com/decode-data/gdt) (pin a specific gdt schema version, don't float against `main` — currently v0.2.0 is the latest tagged release), `sqlglot` (MIT).
**Consumed by:** decode-madflow's Phase 1 sidecar (Rust/Tauri app calls this via a bundled Python process) — a separate integration path from the CLI/Skill below. The sidecar call is decode-madflow's internal `ToolProvider` registration; the CLI/Skill are for external agents (other Claude Code sessions, other tools) working with this package standalone. Keep both working.

## What this is

Three things, not one — the LLM-friendliness goal specifically requires more than a library:

1. **The Python library** — `tag_operations()`, see below.
2. **A CLI** — `madflow-sqlops tag file.sql --dialect snowflake`, outputting gdt JSON to stdout. Makes it usable by an agent operating through a shell tool, not only by Python code that imports it directly.
3. **A bundled `SKILL.md`** (Anthropic Skill format) — ships in this repo, not bolted on separately. Any Claude Code session working against this package should pick it up automatically.

Optional, later — not v0.1: a thin MCP server wrapping `tag_operations` as a tool, for non-shell agent clients. Deferred deliberately, not decided against forever.

**The CLI is also the CI/CD story, not just the agent-friendliness story.** Same binary, two callers: the Tauri app's sidecar, and a direct `pip install madflow-sqlops` step in a CI pipeline — no Tauri, no Rust, no desktop app needed for CI to call it. This is what keeps deployment trivial.

## Non-goals (keep the public API narrow)

- No lineage tracking (that's decode-madflow's concern, consuming this package's output).
- No rule evaluation (that's decode-madflow's rules engine).
- **No ruleset/rules YAML of any kind** — not even a gdt-only one. This package emits tags; it never has an opinion about which tags are allowed where. If a standalone, gdt-native ruleset+verifier ever gets built, it belongs in the [gdt](https://github.com/decode-data/gdt) repo, not here.
- No app-specific types anywhere in the public API — a caller with no knowledge of decode-madflow, dbt, or YAML config should be able to use this package.

`examples/rules_checker/` is reference material for building a rules engine on top of this package's output — not an exception to the above. It's not imported by `madflow_sqlops`, not exported, not shipped in the built wheel (verified). See its own README for why: rule evaluation still belongs in a separate consumer (decode-madflow, most likely), this is just a documented starting point for whoever builds that.

## Architecture

1. **Parse** — `sqlglot.parse_one(sql, dialect=...)` → AST. Dialect matters; don't assume a default.
2. **Tag** — walk the AST once, classify nodes per the [gdt category table](https://github.com/decode-data/gdt), build the output structure.
3. **Cache** — key the tagged output by a hash of the input SQL string (+ dialect). Re-tagging identical input is a cache hit, not a re-parse. Cache *persistence* is the caller's concern — this package just needs cheap, deterministic cache-key computation.
4. **Validate against gdt schema** — output should validate against the pinned gdt JSON Schema version; fail loudly on drift rather than silently emitting an unrecognized shape.

**Classification is 100% structural (AST node types via `isinstance` checks against `sqlglot.exp`), never regex or other string/text matching against the raw SQL.** The name-based categories (`ai_function`/`udf`/`column_hash`'s dialect fallback — see `docs/decisions.md` 0003 in the [gdt](https://github.com/decode-data/gdt) repo) still match against parsed function-name *nodes*, not raw source text. `src/madflow_sqlops/` imports `re` nowhere — verifiable directly: `grep -rn "^import re" src/madflow_sqlops/` returns nothing.

## Public API sketch

```python
from madflow_sqlops import tag_operations

result = tag_operations(sql, dialect="snowflake")
# result.gdt_version == "0.2"
# result.operations.join -> [...]
# result.operations.rename -> [...]
# result.operations.compute -> [...]
```

Keep it this narrow. Resist convenience methods that encode decode-madflow-specific assumptions (e.g. "is this a staging model" — that's a caller-side judgment based on tags/config this package knows nothing about).

## CLI sketch

```
madflow-sqlops tag file.sql --dialect snowflake            # gdt JSON to stdout
madflow-sqlops tag file.sql --dialect snowflake --pretty    # human-readable
echo "SELECT ..." | madflow-sqlops tag - --dialect duckdb   # stdin
```

Same narrow-scope discipline as the library API — no `--staging-check` flags or anything encoding app-specific judgment.

## `SKILL.md`

Ships at `.claude/skills/madflow-sqlops/SKILL.md` (not repo root) so a Claude Code session working in this repo picks it up automatically, per "What this is" above. Covers: frontmatter (name + trigger description), both invocation paths (CLI and Python API), a pointer at the vendored gdt JSON Schema rather than a duplicate of it, and the gotchas (dialect never defaulted, cache-hit responses are structurally identical to fresh tags, output shape lags the latest gdt spec until this package's pin is bumped).

## Testing (planned)

- Fixture-based: one SQL fixture per gdt category (note: `gdt` v0.2 added several categories beyond the original ten — `wildcard_select`, `json_parse`, `json_extract`, `unnest`, `ai_function`, `udf`, `column_hash` — cover all of them, not just the v0.1 set), plus combinations (join + rename + computed column together).
- Golden-file tests against the gdt JSON Schema — every fixture's output must validate.
- Cross-dialect tests where relevant (Snowflake vs. BigQuery vs. DuckDB for the same logical operation) — gdt categories should be dialect-agnostic even though the SQL text isn't.

## Packaging & release

1. Own PyPI package (`madflow-sqlops`), independent versioning from both gdt and decode-madflow.
2. Pin the gdt schema version explicitly (a bundled schema file or constant) — don't fetch it dynamically at runtime.
3. Can release before decode-madflow's own beta — standalone visibility play, not blocked on the app.

**Scaffold status:** `uv build` produces a valid sdist + wheel (`twine check` passes; the vendored gdt schema, `py.typed`, and the `madflow-sqlops` console-script entry point are all confirmed present in the wheel, and both were exercised from a wheel-only install in a clean venv with no source checkout). The `madflow-sqlops` name is unclaimed on PyPI as of this writing. Not yet actually published — `uv publish` is a deliberate, separate step requiring a PyPI API token and explicit sign-off, not bundled into this scaffolding work.

## Dialect/engine normalization — resolved upstream

Previously an open question here; now answered in `gdt`'s `docs/decisions.md` (ADR 0001). Apply that decision as written — don't re-derive it in this repo.

## Status

- [x] Pin gdt schema version (pinned to v0.2.0 — see `src/madflow_sqlops/_version.py`)
- [x] `tag_operations()` implementation
- [x] CLI
- [x] `SKILL.md`
- [x] Test fixtures
- [x] PyPI package scaffold (not yet published — see Packaging & release)
