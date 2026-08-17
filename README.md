# madflow-sqlops — GDTO Reference Implementation

**License:** MIT — matches `sqlglot` exactly (this package extends it directly; matching removes any license-compatibility friction for the existing `sqlglot` community).
**Depends on:** [gdto](https://github.com/decode-data/gdto) (pin a specific GDTO schema version, don't float against `main`), `sqlglot` (MIT).
**Consumed by:** decode-madflow's Phase 1 sidecar (Rust/Tauri app calls this via a bundled Python process) — a separate integration path from the CLI/Skill below. The sidecar call is decode-madflow's internal `ToolProvider` registration; the CLI/Skill are for external agents (other Claude Code sessions, other tools) working with this package standalone. Keep both working.

## What this is

Three things, not one — the LLM-friendliness goal specifically requires more than a library:

1. **The Python library** — `tag_operations()`, see below.
2. **A CLI** — `madflow-sqlops tag file.sql --dialect snowflake`, outputting GDTO JSON to stdout. Makes it usable by an agent operating through a shell tool, not only by Python code that imports it directly.
3. **A bundled `SKILL.md`** (Anthropic Skill format) — ships in this repo, not bolted on separately. Any Claude Code session working against this package should pick it up automatically.

Optional, later — not v0.1: a thin MCP server wrapping `tag_operations` as a tool, for non-shell agent clients. Deferred deliberately, not decided against forever.

**The CLI is also the CI/CD story, not just the agent-friendliness story.** Same binary, two callers: the Tauri app's sidecar, and a direct `pip install madflow-sqlops` step in a CI pipeline — no Tauri, no Rust, no desktop app needed for CI to call it. This is what keeps deployment trivial.

## Non-goals (keep the public API narrow)

- No lineage tracking (that's decode-madflow's concern, consuming this package's output).
- No rule evaluation (that's decode-madflow's rules engine).
- **No ruleset/rules YAML of any kind** — not even a GDTO-only one. This package emits tags; it never has an opinion about which tags are allowed where. If a standalone, GDTO-native ruleset+verifier ever gets built, it belongs in the [gdto](https://github.com/decode-data/gdto) repo, not here.
- No app-specific types anywhere in the public API — a caller with no knowledge of decode-madflow, dbt, or YAML config should be able to use this package.

## Architecture

1. **Parse** — `sqlglot.parse_one(sql, dialect=...)` → AST. Dialect matters; don't assume a default.
2. **Tag** — walk the AST once, classify nodes per the [GDTO category table](https://github.com/decode-data/gdto), build the output structure.
3. **Cache** — key the tagged output by a hash of the input SQL string (+ dialect). Re-tagging identical input is a cache hit, not a re-parse. Cache *persistence* is the caller's concern — this package just needs cheap, deterministic cache-key computation.
4. **Validate against GDTO schema** — output should validate against the pinned GDTO JSON Schema version; fail loudly on drift rather than silently emitting an unrecognized shape.

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
madflow-sqlops tag file.sql --dialect snowflake            # GDTO JSON to stdout
madflow-sqlops tag file.sql --dialect snowflake --pretty    # human-readable
echo "SELECT ..." | madflow-sqlops tag - --dialect duckdb   # stdin
```

Same narrow-scope discipline as the library API — no `--staging-check` flags or anything encoding app-specific judgment.

## `SKILL.md` (planned, not yet written)

Will ship at repo root (or `.claude/skills/madflow-sqlops/SKILL.md`). Outline:

- **Frontmatter:** name, one-line trigger description (working with SQL operation classification, GDTO output, or this package specifically).
- **Invocation:** CLI syntax above, plus the Python API for in-process use.
- **Output shape:** point at the GDTO spec's JSON Schema rather than duplicating it.
- **Gotchas:** dialect must be specified explicitly (no silent default); a cache-hit response is structurally identical to a fresh tag; GDTO version pinning means output shape can lag behind the latest spec until this package is updated.

## Testing (planned)

- Fixture-based: one SQL fixture per GDTO category, plus combinations (join + rename + computed column together).
- Golden-file tests against the GDTO JSON Schema — every fixture's output must validate.
- Cross-dialect tests where relevant (Snowflake vs. BigQuery vs. DuckDB for the same logical operation) — GDTO categories should be dialect-agnostic even though the SQL text isn't.

## Packaging & release

1. Own PyPI package (`madflow-sqlops`), independent versioning from both GDTO and decode-madflow.
2. Pin the GDTO schema version explicitly (a bundled schema file or constant) — don't fetch it dynamically at runtime.
3. Can release before decode-madflow's own beta — standalone visibility play, not blocked on the app.

## Open question to resolve before v0.1 release

`sqlglot`'s AST includes dialect-specific node subclasses in places — decide whether GDTO tagging normalizes across dialects at this layer (recommended: yes) or whether dialect-specific detail is preserved and normalization is pushed to callers. This should be raised and answered in the [gdto](https://github.com/decode-data/gdto) repo first, not decided unilaterally here.

## Status

- [ ] JSON Schema pinned from gdto (blocked on gdto finalizing v0.1 schema)
- [ ] `tag_operations()` implementation
- [ ] CLI
- [ ] `SKILL.md`
- [ ] Test fixtures
- [ ] PyPI package scaffold
