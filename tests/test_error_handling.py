"""Documents current (undecorated) behavior for invalid input.

tag_operations() doesn't wrap or translate sqlglot's own exceptions -- an
unparseable dialect name or unparseable SQL propagates sqlglot's error type
as-is. These tests pin that behavior down so it can't drift silently; they
aren't asserting it's the *right* long-term behavior (a future PR might want
a dedicated madflow_sqlops exception type), just the current one.
"""

from __future__ import annotations

import pytest
import sqlglot.errors

from madflow_sqlops import tag_operations


def test_unknown_dialect_raises_sqlglot_value_error():
    with pytest.raises(ValueError, match="Unknown dialect"):
        tag_operations("SELECT 1", dialect="not-a-real-dialect")


def test_unparseable_sql_raises_sqlglot_parse_error():
    with pytest.raises(sqlglot.errors.ParseError):
        tag_operations("SELECT FROM WHERE", dialect="")


def test_empty_sql_raises():
    with pytest.raises(sqlglot.errors.ParseError):
        tag_operations("", dialect="")
