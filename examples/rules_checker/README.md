# Reference: building a rules checker on top of `tag_operations()`

**This is example/reference material, not part of the published package.**
Nothing under `examples/` is imported by `madflow_sqlops`, exported from its
public API, or shipped in the built wheel. It exists so whoever eventually
builds a real rules engine (decode-madflow's, most likely, per this repo's
own README -> Non-goals: "No rule evaluation — that's decode-madflow's
rules engine") has a concrete starting point instead of a blank page.

See `reference.py` for a small, runnable illustration of the pattern below.

## The shape of the problem

`tag_operations()` emits *facts* about a query -- what joins exist, what's
computed, which CTEs are present, and so on. A rules checker asks a
different question: *are those facts what this project wants to see?*
"At most one join per CTE," "no inline subqueries," "CTEs must be named
`stg_*`/`int_*`/`fct_*`" are all policy, not structure -- exactly why this
package doesn't (and per its own design, shouldn't) answer them itself.

The pattern that keeps the boundary clean:

```
SQL --tag_operations()--> gdt-tagged JSON --evaluate(rules)--> violations
```

The rules checker is a **separate** consumer: it takes a `TaggedResult` (or
its `.to_dict()`) plus a rules config, and produces a list of violations.
It never touches SQL or `sqlglot` directly -- if a rule needs information
`tag_operations()` doesn't expose, that's a gap in the *gdt spec*, not
something to patch around with regex on the raw SQL text in the rules layer
either (see [decode-data/gdt#13](https://github.com/decode-data/gdt/issues/13)
for exactly this situation).

## What's checkable today vs. what's blocked

Every category in gdt v0.2 is flat per query -- an entry doesn't know which
CTE (if any) it came from. That's the load-bearing limitation for this whole
design. Concretely, from the motivating examples this reference was written
against:

| Rule | Checkable today? | How |
|---|---|---|
| No inline/nested subqueries | Yes | `subquery_cte` entries with `kind: "subquery"` |
| No subqueries in `WHERE` | Yes | `subquery_cte` entries with `location: "where"` |
| CTE naming convention | Yes | `subquery_cte` entries' `alias` field (`kind: "cte"`) |
| At most 1 join per CTE | **No** | needs per-entry CTE attribution -- [gdt#13](https://github.com/decode-data/gdt/issues/13) |
| No business logic outside CTEs | **No** | same gap |

Don't build around the gap with heuristics (e.g. "assume the Nth join
belongs to the Nth CTE by textual order") -- that's fragile in exactly the
way this whole project has spent two review passes fixing. Wait for the
schema to carry the real answer, or don't check that rule yet.

## Suggested shape for a rules config

Declarative, not code -- so non-engineers can read/edit the rule list, and
so the evaluator stays generic instead of accumulating one bespoke function
per rule. One reasonable shape (see `reference.py` for the matching
evaluator):

```yaml
rules:
  - id: cte-naming-convention
    category: subquery_cte
    check: alias_matches_pattern
    params:
      kind: cte
      pattern: "^(stg|int|fct|dim)_"
    severity: error
    message: "CTE '{alias}' doesn't match the stg_/int_/fct_/dim_ naming convention"

  - id: no-inline-subqueries
    category: subquery_cte
    check: forbid_kind
    params:
      kind: subquery
    severity: error
    message: "Inline subquery (alias={alias}) -- use a named CTE instead"

  - id: no-subqueries-in-where
    category: subquery_cte
    check: forbid_location
    params:
      location: where
    severity: warning
    message: "Subquery in WHERE clause -- prefer a CTE + join"

  # Not implementable yet -- needs gdt#13's per-entry CTE-scope field.
  # Included here so the shape is ready the moment that field exists.
  - id: one-join-per-cte
    category: join
    check: max_count_per_scope
    params:
      max: 1
    severity: error
    message: "CTE '{scope}' has {count} joins (max 1)"
```

Each rule names a gdt `category` to scan, a `check` (one of a small,
generic set the evaluator implements -- not one bespoke function per rule),
and `params` for that check. `severity` and `message` are for the UI layer
to render, not for the evaluator to interpret.

## Evaluator sketch

`reference.py` implements exactly the three "checkable today" check types
above (`alias_matches_pattern`, `forbid_kind`, `forbid_location`) against a
real `tag_operations()` call, plus a `list_violations()` function that
returns structured results (rule id, message, the offending entry) rather
than just printing. Run it directly (`python reference.py`) to see it work
against an inline example query.

Deliberately not built out further than this: no rule-config file loader,
no CLI, no test suite, no packaging. This is a pattern to start from, not a
library to depend on -- copy it into wherever the real rules engine ends up
living (decode-madflow, most likely) and grow it against real project rules
as they show up, rather than speculatively generalizing now for rules that
don't exist yet.
