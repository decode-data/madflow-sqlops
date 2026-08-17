from __future__ import annotations

import json

import pytest

from madflow_sqlops import tag_operations
from madflow_sqlops.cli import main

SQL = "SELECT cust_id AS customer_id FROM raw_customers"


def test_tag_file_prints_compact_json_matching_the_library(tmp_path, capsys):
    sql_file = tmp_path / "q.sql"
    sql_file.write_text(SQL)

    exit_code = main(["tag", str(sql_file), "--dialect", "snowflake"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert json.loads(out) == tag_operations(SQL, dialect="snowflake").to_dict()
    assert "\n  " not in out  # compact by default, no indentation


def test_tag_pretty_indents_the_output(tmp_path, capsys):
    sql_file = tmp_path / "q.sql"
    sql_file.write_text(SQL)

    exit_code = main(["tag", str(sql_file), "--dialect", "snowflake", "--pretty"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "\n  " in out
    assert json.loads(out) == tag_operations(SQL, dialect="snowflake").to_dict()


def test_tag_reads_from_stdin(monkeypatch, capsys):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(SQL))

    exit_code = main(["tag", "-", "--dialect", "duckdb"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert json.loads(out) == tag_operations(SQL, dialect="duckdb").to_dict()


def test_missing_dialect_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["tag", "somefile.sql"])
    assert exc_info.value.code == 2
    assert "--dialect" in capsys.readouterr().err


def test_nonexistent_file_is_a_friendly_error(capsys):
    exit_code = main(["tag", "does-not-exist.sql", "--dialect", "snowflake"])
    assert exit_code == 1
    assert "no such file" in capsys.readouterr().err.lower()


def test_unparseable_sql_is_a_friendly_error(tmp_path, capsys):
    sql_file = tmp_path / "bad.sql"
    sql_file.write_text("SELECT FROM WHERE")

    exit_code = main(["tag", str(sql_file), "--dialect", "snowflake"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "madflow-sqlops:" in err


def test_unknown_dialect_is_a_friendly_error(tmp_path, capsys):
    sql_file = tmp_path / "q.sql"
    sql_file.write_text(SQL)

    exit_code = main(["tag", str(sql_file), "--dialect", "not-a-real-dialect"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "unknown dialect" in err.lower()
