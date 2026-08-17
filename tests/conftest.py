from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

FIXTURES_ROOT = Path(__file__).parent / "fixtures"


@dataclass(frozen=True)
class DocumentFixture:
    """One .sql/.json pair -- .json holds the full expected `operations` dict."""

    name: str
    sql: str
    dialect: str
    expected_operations: dict

    @classmethod
    def load(cls, sql_path: Path) -> "DocumentFixture":
        dialect, sql = _parse_sql_file(sql_path)
        expected = json.loads(sql_path.with_suffix(".json").read_text())
        return cls(name=sql_path.stem, sql=sql, dialect=dialect, expected_operations=expected)


@dataclass(frozen=True)
class DialectVariant:
    """One entry in a cross-dialect group -- .json holds only the shared category's expected list."""

    group: str
    label: str
    sql: str
    dialect: str
    category: str
    expected_entries: list


def _parse_sql_file(sql_path: Path) -> tuple[str, str]:
    text = sql_path.read_text()
    first_line, _, rest = text.partition("\n")
    prefix = "-- dialect:"
    if not first_line.startswith(prefix):
        raise ValueError(f"{sql_path} must start with '{prefix} <name>' (empty string for no dialect)")
    return first_line[len(prefix) :].strip(), rest.strip("\n")


def discover_document_fixtures(subdir: str) -> list[DocumentFixture]:
    directory = FIXTURES_ROOT / subdir
    return [DocumentFixture.load(p) for p in sorted(directory.glob("*.sql"))]


def discover_dialect_variants() -> list[DialectVariant]:
    directory = FIXTURES_ROOT / "dialects"
    variants = []
    for sql_path in sorted(directory.glob("*__*.sql")):
        group, _, label = sql_path.stem.partition("__")
        dialect, sql = _parse_sql_file(sql_path)
        expected_entries = json.loads((directory / f"{group}.json").read_text())
        variants.append(
            DialectVariant(
                group=group,
                label=label,
                sql=sql,
                dialect=dialect,
                category=group,
                expected_entries=expected_entries,
            )
        )
    return variants


def pytest_generate_tests(metafunc):
    if "category_fixture" in metafunc.fixturenames:
        fixtures = discover_document_fixtures("categories")
        metafunc.parametrize("category_fixture", fixtures, ids=[f.name for f in fixtures])
    elif "combination_fixture" in metafunc.fixturenames:
        fixtures = discover_document_fixtures("combinations")
        metafunc.parametrize("combination_fixture", fixtures, ids=[f.name for f in fixtures])
    elif "dialect_variant" in metafunc.fixturenames:
        variants = discover_dialect_variants()
        ids = [f"{v.group}-{v.label}" for v in variants]
        metafunc.parametrize("dialect_variant", variants, ids=ids)
