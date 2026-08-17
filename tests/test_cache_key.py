from __future__ import annotations

from madflow_sqlops import cache_key, tag_operations


def test_same_sql_and_dialect_produce_the_same_key():
    sql = "SELECT * FROM orders"
    assert cache_key(sql, "snowflake") == cache_key(sql, "snowflake")


def test_different_sql_produces_a_different_key():
    assert cache_key("SELECT * FROM orders", "snowflake") != cache_key(
        "SELECT * FROM customers", "snowflake"
    )


def test_different_dialect_produces_a_different_key():
    sql = "SELECT * FROM orders"
    assert cache_key(sql, "snowflake") != cache_key(sql, "bigquery")


def test_tagged_result_cache_key_matches_the_pure_function():
    sql = "SELECT * FROM orders"
    result = tag_operations(sql, dialect="duckdb")
    assert result.cache_key == cache_key(sql, "duckdb")
