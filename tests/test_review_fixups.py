"""Regression tests for the correctness bugs found by the post-merge code
review (see PR description for the review methodology). Each test uses the
literal failure-scenario SQL the review verified was broken, and asserts the
previously wrong/missing/crashing behavior is now correct -- not just "no
crash" where the original bug was about silently wrong data.
"""

from __future__ import annotations

import jsonschema.exceptions

from madflow_sqlops import tag_operations
from madflow_sqlops.cli import main as cli_main


def test_semi_join_is_omitted_not_crashed(capsys):
    # SEMI/ANTI/bare-OUTER map to no gdt join.kind enum value -- a known
    # representability gap (like non-equi joins), not something to guess at.
    # Must not raise, and must not emit an invalid `kind`.
    result = tag_operations("SELECT * FROM a SEMI JOIN b ON a.id = b.id", dialect="bigquery")
    assert result.operations.join == []


def test_anti_join_is_omitted_not_crashed():
    result = tag_operations("SELECT * FROM a ANTI JOIN b ON a.id = b.id", dialect="bigquery")
    assert result.operations.join == []


def test_nested_join_tree_is_not_dropped():
    result = tag_operations(
        "SELECT * FROM a JOIN (b JOIN c ON b.id = c.id) ON a.id = b.id", dialect=""
    )
    assert result.operations.join == [
        {"kind": "inner", "tables": ["a", "b"], "keys": ["id"]},
        {"kind": "inner", "tables": ["b", "c"], "keys": ["id"]},
    ]


def test_deeply_nested_join_tree_terminates_and_is_correct():
    # Regression guard for the infinite-recursion bug hit while fixing the
    # above -- must terminate, and must find every level.
    result = tag_operations(
        "SELECT * FROM a JOIN (b JOIN (c JOIN d ON c.id = d.id) ON b.id = c.id) ON a.id = b.id",
        dialect="",
    )
    assert len(result.operations.join) == 3


def test_join_using_gets_keys():
    result = tag_operations("SELECT * FROM a JOIN b USING(id)", dialect="")
    assert result.operations.join == [{"kind": "inner", "tables": ["a", "b"], "keys": ["id"]}]


def test_three_level_qualified_udf_keeps_every_segment():
    result = tag_operations(
        "SELECT my_project.my_dataset.normalize_phone(x) AS y FROM t", dialect="bigquery"
    )
    assert result.operations.udf[0]["function"] == "my_project.my_dataset.normalize_phone"


def test_multi_column_distinct_keeps_every_column():
    result = tag_operations("SELECT COUNT(DISTINCT a, b) FROM t", dialect="")
    entry = result.operations.aggregate[0]
    assert entry["argument_summary"] == "a, b"
    assert entry["source_columns"] == ["a", "b"]


def test_two_argument_aggregate_keeps_second_column():
    result = tag_operations("SELECT CORR(x, y) AS c FROM t", dialect="")
    entry = result.operations.aggregate[0]
    assert entry["source_columns"] == ["x", "y"]


def test_scalar_subquery_in_select_list_is_not_labeled_from():
    result = tag_operations(
        "SELECT (SELECT MAX(order_date) FROM orders o WHERE o.customer_id = c.id) "
        "AS last_order FROM customers c",
        dialect="",
    )
    assert result.operations.subquery_cte[0]["location"] != "from"


def test_cast_to_variant_does_not_flip_json_extract_scalar():
    result = tag_operations(
        "SELECT CAST(payload:address AS VARIANT) AS address_json FROM events",
        dialect="snowflake",
    )
    assert result.operations.json_extract[0]["scalar"] is False


def test_cast_to_string_still_flips_json_extract_scalar():
    # The documented positive case (docs/grammar.md) must keep working.
    result = tag_operations(
        "SELECT payload:email::string AS user_email FROM events", dialect="snowflake"
    )
    assert result.operations.json_extract[0]["scalar"] is True


def test_ignore_nulls_window_reports_the_real_function_name():
    result = tag_operations(
        "SELECT SUM(x) IGNORE NULLS OVER (PARTITION BY g) AS y FROM tbl", dialect="snowflake"
    )
    assert result.operations.window[0]["function"] == "sum"


def test_ignore_nulls_window_does_not_duplicate_as_aggregate():
    result = tag_operations(
        "SELECT SUM(x) IGNORE NULLS OVER (PARTITION BY g) AS y FROM tbl", dialect="snowflake"
    )
    assert result.operations.window
    assert result.operations.aggregate == []


def test_json_path_array_subscript_is_distinct_from_no_subscript():
    with_subscript = tag_operations(
        "SELECT payload -> 'a' -> 0 ->> 'b' AS x FROM t", dialect="postgres"
    )
    without_subscript = tag_operations(
        "SELECT payload -> 'a' -> 'zero' ->> 'b' AS x FROM t", dialect="postgres"
    )
    assert with_subscript.operations.json_extract[0]["path"] == "$.a[0].b"
    assert without_subscript.operations.json_extract[0]["path"] == "$.a.zero.b"
    assert with_subscript.operations.json_extract[0]["path"] != without_subscript.operations.json_extract[0]["path"]


def test_multi_array_unnest_captures_every_array():
    result = tag_operations(
        "SELECT o.order_id, tag FROM orders o, UNNEST(o.tags1, o.tags2) AS t(tag1, tag2)",
        dialect="postgres",
    )
    assert len(result.operations.unnest) == 2
    assert result.operations.unnest[0]["source_summary"] == "o.tags1"
    assert result.operations.unnest[0]["alias"] == "tag1"
    assert result.operations.unnest[1]["source_summary"] == "o.tags2"
    assert result.operations.unnest[1]["alias"] == "tag2"


def test_group_by_rollup_still_reports_group_by_keys():
    result = tag_operations("SELECT a, b, SUM(c) AS s FROM t GROUP BY ROLLUP(a, b)", dialect="")
    assert result.operations.aggregate[0]["group_by_keys"] == ["a", "b"]


def test_group_by_cube_still_reports_group_by_keys():
    result = tag_operations("SELECT a, b, SUM(c) AS s FROM t GROUP BY CUBE(a, b)", dialect="")
    assert result.operations.aggregate[0]["group_by_keys"] == ["a", "b"]


def test_group_by_grouping_sets_still_reports_group_by_keys():
    result = tag_operations(
        "SELECT a, b, SUM(c) AS s FROM t GROUP BY GROUPING SETS ((a), (b), ())", dialect=""
    )
    assert result.operations.aggregate[0]["group_by_keys"] == ["a", "b"]


def test_sha2_non_literal_bit_length_does_not_crash():
    result = tag_operations("SELECT SHA2(payload, bits_col) AS h FROM t", dialect="snowflake")
    entry = result.operations.column_hash[0]
    assert "algorithm_bits" not in entry


def test_sha2_literal_bit_length_still_reported():
    result = tag_operations("SELECT SHA2(email, 256) AS h FROM t", dialect="")
    assert result.operations.column_hash[0]["algorithm_bits"] == 256


def test_cli_reports_schema_validation_errors_as_a_friendly_message(monkeypatch, capsys):
    import io

    def _raise(*args, **kwargs):
        raise jsonschema.exceptions.ValidationError("simulated schema drift")

    monkeypatch.setattr("madflow_sqlops.cli.tag_operations", _raise)
    monkeypatch.setattr("sys.stdin", io.StringIO("SELECT 1"))
    exit_code = cli_main(["tag", "-", "--dialect", "snowflake"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "madflow-sqlops:" in err
    assert "simulated schema drift" in err
