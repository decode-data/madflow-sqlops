from __future__ import annotations

from madflow_sqlops import GDT_SCHEMA_VERSION, GDT_TAG, tag_operations
from madflow_sqlops._schema_validation import load_schema


def test_pinned_schema_version_matches_the_vendored_schema_const():
    schema = load_schema()
    assert schema["properties"]["gdt_version"]["const"] == GDT_SCHEMA_VERSION


def test_pinned_tag_is_the_v0_2_line():
    # The vendored schema file keeps the "v0.1" filename by upstream
    # convention (see _schema_validation.py) -- this asserts the *tag*, not
    # the filename, actually matches the schema content's own version.
    assert GDT_TAG == "v0.2.0"
    assert GDT_SCHEMA_VERSION == "0.2"


def test_tag_operations_emits_the_pinned_version():
    result = tag_operations("SELECT 1", dialect="")
    assert result.gdt_version == GDT_SCHEMA_VERSION
