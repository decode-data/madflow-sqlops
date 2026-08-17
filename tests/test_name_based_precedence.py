"""Precedence between the three name-based categories (docs/decisions.md, 0003).

The real AI_FUNCTION_NAMES/COLUMN_HASH_FALLBACK_NAMES allowlists don't
currently share any entry, so nothing in the fixture suite actually exercises
the *order* column_hash/ai_function/udf are checked in -- only that each one
independently works. These tests monkeypatch the allowlists to force a
collision, so the precedence rule in _categories._add_name_based is pinned
down by an actual assertion rather than "no known collision exists yet".
"""

from __future__ import annotations

from madflow_sqlops import _categories, tag_operations

_COLLIDING_NAME = "collide_test_fn"
_SQL = f"SELECT {_COLLIDING_NAME}(email) AS x FROM t"


def test_column_hash_fallback_takes_precedence_over_ai_function(monkeypatch):
    monkeypatch.setattr(_categories, "COLUMN_HASH_FALLBACK_NAMES", frozenset({_COLLIDING_NAME}))
    monkeypatch.setattr(_categories, "AI_FUNCTION_NAMES", frozenset({_COLLIDING_NAME}))

    result = tag_operations(_SQL, dialect="")

    assert [e["function"] for e in result.operations.column_hash] == [_COLLIDING_NAME]
    assert result.operations.ai_function == []
    assert result.operations.udf == []


def test_ai_function_takes_precedence_over_udf(monkeypatch):
    monkeypatch.setattr(_categories, "COLUMN_HASH_FALLBACK_NAMES", frozenset())
    monkeypatch.setattr(_categories, "AI_FUNCTION_NAMES", frozenset({_COLLIDING_NAME}))

    result = tag_operations(_SQL, dialect="")

    assert [e["function"] for e in result.operations.ai_function] == [_COLLIDING_NAME]
    assert result.operations.column_hash == []
    assert result.operations.udf == []


def test_unmatched_anonymous_call_falls_back_to_udf(monkeypatch):
    monkeypatch.setattr(_categories, "COLUMN_HASH_FALLBACK_NAMES", frozenset())
    monkeypatch.setattr(_categories, "AI_FUNCTION_NAMES", frozenset())

    result = tag_operations(_SQL, dialect="")

    assert [e["function"] for e in result.operations.udf] == [_COLLIDING_NAME]
    assert result.operations.column_hash == []
    assert result.operations.ai_function == []
