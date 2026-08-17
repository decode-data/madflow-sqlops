"""One fixture per gdt v0.2 category -- see tests/fixtures/categories/.

Each fixture's expected output is checked both for an exact match against the
golden JSON and for validity against the vendored gdt schema, so a fixture
can never silently drift into an invalid shape.
"""

from __future__ import annotations

from madflow_sqlops import tag_operations
from madflow_sqlops._schema_validation import validate


def test_category_fixture_matches_golden_output(category_fixture):
    result = tag_operations(category_fixture.sql, dialect=category_fixture.dialect)
    assert result.operations.to_dict() == category_fixture.expected_operations


def test_category_fixture_validates_against_schema(category_fixture):
    result = tag_operations(category_fixture.sql, dialect=category_fixture.dialect)
    validate(result.to_dict())  # raises on drift; also exercised inside tag_operations itself


def test_all_categories_have_a_fixture(request):
    from madflow_sqlops._categories import CATEGORY_NAMES

    from .conftest import discover_document_fixtures

    fixture_names = {f.name for f in discover_document_fixtures("categories")}
    missing = set(CATEGORY_NAMES) - fixture_names
    assert not missing, f"missing category fixtures for: {sorted(missing)}"
