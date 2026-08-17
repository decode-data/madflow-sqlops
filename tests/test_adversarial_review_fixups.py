"""Regression tests for the adversarial-review findings (a second pass, run
after the first bug-fix PR, targeting robustness/crash-safety rather than
AST misclassification). Each test uses the literal failure-scenario input
the review verified was broken.
"""

from __future__ import annotations

import dataclasses
import io

import pytest
import sqlglot.errors

from madflow_sqlops import cache_key, tag_operations
from madflow_sqlops._categories import CATEGORY_NAMES
from madflow_sqlops._result import Operations
from madflow_sqlops.cli import main as cli_main


def test_deeply_nested_parens_do_not_crash_the_cli(tmp_path, capsys):
    sql = "SELECT " + "(" * 100 + "1" + ")" * 100
    sql_file = tmp_path / "deep.sql"
    sql_file.write_text(sql)

    exit_code = cli_main(["tag", str(sql_file), "--dialect", "duckdb"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert err.startswith("madflow-sqlops:")
    assert "Traceback" not in err


def test_unreadable_file_does_not_crash_the_cli(tmp_path, capsys):
    sql_file = tmp_path / "noperm.sql"
    sql_file.write_text("SELECT 1")
    sql_file.chmod(0o000)
    try:
        exit_code = cli_main(["tag", str(sql_file), "--dialect", "duckdb"])
    finally:
        sql_file.chmod(0o644)

    assert exit_code == 1
    err = capsys.readouterr().err
    assert err.startswith("madflow-sqlops:")
    assert "Traceback" not in err


def test_non_utf8_file_does_not_crash_the_cli(tmp_path, capsys):
    sql_file = tmp_path / "bad_encoding.sql"
    sql_file.write_bytes(b"\xff\xfeSELECT 1")

    exit_code = cli_main(["tag", str(sql_file), "--dialect", "duckdb"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert err.startswith("madflow-sqlops:")
    assert "Traceback" not in err


def test_blank_dialect_is_a_cli_usage_error(tmp_path, capsys):
    sql_file = tmp_path / "q.sql"
    sql_file.write_text("SELECT 1")

    with pytest.raises(SystemExit) as exc_info:
        cli_main(["tag", str(sql_file), "--dialect", ""])
    assert exc_info.value.code == 2
    assert "--dialect" in capsys.readouterr().err


def test_whitespace_dialect_is_a_cli_usage_error(tmp_path, capsys):
    sql_file = tmp_path / "q.sql"
    sql_file.write_text("SELECT 1")

    with pytest.raises(SystemExit):
        cli_main(["tag", str(sql_file), "--dialect", "   "])


def test_blank_dialect_is_accepted_by_the_library_as_generic_ansi():
    # Deliberately the opposite assertion from the CLI test above -- dialect=""
    # is a long-established, intentional convention throughout this package's
    # own test suite for "generic/ANSI, no specific dialect." The CLI rejects
    # a blank --dialect as a likely-accidental empty flag value; the library
    # function itself must keep accepting it, since there's no *implicit*
    # default here (the parameter has no default value) -- "" is a real,
    # explicit choice a caller can deliberately make.
    result = tag_operations("SELECT 1", dialect="")
    assert result.gdt_version == "0.2"


def test_multi_statement_sql_is_rejected_not_silently_merged():
    with pytest.raises(ValueError, match="exactly one SQL statement"):
        tag_operations(
            "SELECT a.id FROM customers a JOIN orders b ON a.id=b.cust_id; "
            "SELECT SUM(amount) AS total FROM orders GROUP BY region;",
            dialect="duckdb",
        )


def test_single_statement_with_trailing_semicolon_still_works():
    result = tag_operations("SELECT 1;", dialect="")
    assert result.gdt_version == "0.2"


def test_stray_extra_semicolons_still_work():
    result = tag_operations("SELECT 1;;;", dialect="")
    assert result.gdt_version == "0.2"


def test_empty_sql_still_raises_parse_error():
    with pytest.raises(sqlglot.errors.ParseError):
        tag_operations("", dialect="")


def test_to_dict_returns_independent_copies_not_references():
    result = tag_operations("SELECT cust_id AS customer_id FROM t", dialect="")
    d1 = result.to_dict()
    d1["operations"]["rename"][0]["source"] = "MUTATED"
    d2 = result.to_dict()
    assert d2["operations"]["rename"][0]["source"] == "cust_id"
    assert d1["operations"]["rename"] is not result.operations.rename


def test_operations_to_dict_returns_independent_copies():
    result = tag_operations("SELECT cust_id AS customer_id FROM t", dialect="")
    d1 = result.operations.to_dict()
    d1["rename"].append({"source": "FAKE", "output": "FAKE"})
    d2 = result.operations.to_dict()
    assert d2["rename"] == [{"source": "cust_id", "output": "customer_id"}]


def test_cache_key_does_not_collide_on_ambiguous_separator():
    assert cache_key("b:c", "a") != cache_key("c", "a:b")


def test_cache_key_still_deterministic():
    assert cache_key("snowflake", "SELECT 1") == cache_key("snowflake", "SELECT 1")


def test_cache_key_still_differs_by_dialect_and_sql():
    assert cache_key("snowflake", "SELECT 1") != cache_key("bigquery", "SELECT 1")
    assert cache_key("snowflake", "SELECT 1") != cache_key("snowflake", "SELECT 2")


def test_category_names_and_operations_fields_stay_in_sync():
    # Guards the two-places-to-update risk flagged by the review: CATEGORY_NAMES
    # (_categories.py) and Operations's dataclass fields (_result.py) have no
    # shared source of truth and must be kept manually in sync.
    dataclass_fields = {f.name for f in dataclasses.fields(Operations)}
    assert set(CATEGORY_NAMES) == dataclass_fields


def test_schema_validator_is_cached_across_calls():
    from madflow_sqlops._schema_validation import _validator

    assert _validator() is _validator()


def test_reading_from_stdin_still_works_after_moving_read_inside_try(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("SELECT cust_id AS customer_id FROM t"))
    exit_code = cli_main(["tag", "-", "--dialect", "duckdb"])
    assert exit_code == 0
    assert '"customer_id"' in capsys.readouterr().out
