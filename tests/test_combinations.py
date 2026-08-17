"""Multi-category fixtures -- see tests/fixtures/combinations/.

Covers ADR 0002 (compute and the structural-signal categories are
independent, not mutually exclusive) with the CASE-as-compute-and-conditional
and aliased-aggregate-as-aggregate-and-compute examples from
../gdt/docs/decisions.md and docs/grammar.md.
"""

from __future__ import annotations

from madflow_sqlops import tag_operations
from madflow_sqlops._schema_validation import validate


def test_combination_fixture_matches_golden_output(combination_fixture):
    result = tag_operations(combination_fixture.sql, dialect=combination_fixture.dialect)
    assert result.operations.to_dict() == combination_fixture.expected_operations


def test_combination_fixture_validates_against_schema(combination_fixture):
    result = tag_operations(combination_fixture.sql, dialect=combination_fixture.dialect)
    validate(result.to_dict())


def test_case_produces_both_compute_and_conditional():
    result = tag_operations(
        "SELECT CASE WHEN status = 'active' THEN 1 ELSE 0 END AS is_active FROM users",
        dialect="",
    )
    assert result.operations.compute
    assert result.operations.conditional


def test_aliased_aggregate_produces_both_aggregate_and_compute():
    result = tag_operations("SELECT SUM(amount) AS total_spent FROM orders", dialect="")
    assert result.operations.aggregate
    assert result.operations.compute
