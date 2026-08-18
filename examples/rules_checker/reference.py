"""Illustrative sketch of a rules checker built on top of tag_operations().

NOT part of the madflow_sqlops package -- not imported by it, not exported,
not shipped in the built wheel. See README.md in this directory for the
design rationale and what's checkable today vs. blocked on a gdt spec
change (gdt#13).

Run directly to see it evaluate a few rules against an example query:

    python examples/rules_checker/reference.py
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable

from madflow_sqlops import TaggedResult, tag_operations


@dataclass(frozen=True)
class Violation:
    rule_id: str
    severity: str
    message: str
    entry: dict[str, Any]


# --- the three check types this sketch implements -----------------------------------------
# Each takes (entry, params) and returns True if the entry VIOLATES the rule.
# Deliberately small and generic -- add a new check type here only when a
# real rule needs one, not speculatively.


def _check_alias_matches_pattern(entry: dict[str, Any], params: dict[str, Any]) -> bool:
    if entry.get("kind") != params.get("kind"):
        return False  # rule doesn't apply to this entry (e.g. a subquery, not a cte)
    alias = entry.get("alias", "")
    return not re.match(params["pattern"], alias)


def _check_forbid_kind(entry: dict[str, Any], params: dict[str, Any]) -> bool:
    return entry.get("kind") == params.get("kind")


def _check_forbid_location(entry: dict[str, Any], params: dict[str, Any]) -> bool:
    return entry.get("location") == params.get("location")


CHECKS: dict[str, Callable[[dict[str, Any], dict[str, Any]], bool]] = {
    "alias_matches_pattern": _check_alias_matches_pattern,
    "forbid_kind": _check_forbid_kind,
    "forbid_location": _check_forbid_location,
    # "max_count_per_scope" intentionally absent -- needs gdt#13's per-entry
    # CTE-scope field, which doesn't exist yet. A rule using it will raise
    # KeyError from evaluate() below rather than silently no-op.
}


def evaluate(result: TaggedResult, rules: list[dict[str, Any]]) -> list[Violation]:
    """Evaluate `rules` (see README.md for the config shape) against a
    tagged result. Returns one Violation per rule per offending entry.
    """
    operations = result.to_dict()["operations"]
    violations = []
    for rule in rules:
        check_fn = CHECKS[rule["check"]]  # KeyError -> unimplemented check, fail loudly
        entries = operations.get(rule["category"], [])
        for entry in entries:
            if check_fn(entry, rule["params"]):
                # Most gdt fields are optional (e.g. subquery_cte's `alias` is
                # absent for an unaliased derived table) -- format_map with a
                # defaultdict renders a missing field as "?" instead of
                # crashing the whole evaluation over one message template.
                message = rule["message"].format_map(defaultdict(lambda: "?", entry))
                violations.append(
                    Violation(
                        rule_id=rule["id"],
                        severity=rule["severity"],
                        message=message,
                        entry=entry,
                    )
                )
    return violations


# --- demo ------------------------------------------------------------------------------------

EXAMPLE_RULES = [
    {
        "id": "cte-naming-convention",
        "category": "subquery_cte",
        "check": "alias_matches_pattern",
        "params": {"kind": "cte", "pattern": r"^(stg|int|fct|dim)_"},
        "severity": "error",
        "message": "CTE '{alias}' doesn't match the stg_/int_/fct_/dim_ naming convention",
    },
    {
        "id": "no-inline-subqueries",
        "category": "subquery_cte",
        "check": "forbid_kind",
        "params": {"kind": "subquery"},
        "severity": "error",
        "message": "Inline subquery (alias={alias}) -- use a named CTE instead",
    },
    {
        "id": "no-subqueries-in-where",
        "category": "subquery_cte",
        "check": "forbid_location",
        "params": {"location": "where"},
        "severity": "warning",
        "message": "Subquery in WHERE clause -- prefer a CTE + join",
    },
]

EXAMPLE_SQL = """
with recent_orders as (
    select * from raw.orders where order_date > '2026-01-01'
), enriched as (
    select
        recent_orders.*,
        (select count(*) from raw.refunds where refunds.order_id = recent_orders.order_id) as refund_count
    from recent_orders
    where customer_id in (select customer_id from raw.flagged_customers)
)
select * from enriched
"""


def main() -> None:
    result = tag_operations(EXAMPLE_SQL, dialect="snowflake")
    violations = evaluate(result, EXAMPLE_RULES)

    print(f"{len(violations)} violation(s):\n")
    for v in violations:
        print(f"[{v.severity}] {v.rule_id}: {v.message}")


if __name__ == "__main__":
    main()
