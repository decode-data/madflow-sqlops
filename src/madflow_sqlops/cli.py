"""madflow-sqlops CLI -- see README -> CLI sketch.

Same narrow-scope discipline as the library API: this is a thin wrapper
around tag_operations(), nothing more. No --staging-check flags or anything
encoding app-specific judgment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import jsonschema.exceptions
import sqlglot.errors

from .tagging import tag_operations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="madflow-sqlops")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tag_parser = subparsers.add_parser("tag", help="Tag a SQL file's operations against gdt")
    tag_parser.add_argument("file", help="Path to a .sql file, or '-' to read from stdin")
    tag_parser.add_argument("--dialect", required=True, help="sqlglot dialect, e.g. snowflake, bigquery, duckdb")
    tag_parser.add_argument("--pretty", action="store_true", help="Indent the JSON output for human reading")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.dialect.strip():
        # argparse's own required=True only checks the flag was *supplied*,
        # not that its value is non-blank -- a blank value (e.g. from an
        # unset/empty shell variable: `--dialect "$DIALECT"`) would otherwise
        # silently fall through to sqlglot's generic no-dialect parser,
        # defeating "dialect is required and never defaulted" without any
        # warning. Treated as a usage error, same as a missing --dialect.
        parser.error("argument --dialect: value must not be blank")

    try:
        if args.file == "-":
            sql = sys.stdin.read()
        else:
            path = Path(args.file)
            if not path.is_file():
                print(f"madflow-sqlops: no such file: {args.file}", file=sys.stderr)
                return 1
            sql = path.read_text()

        result = tag_operations(sql, dialect=args.dialect)
    except (
        sqlglot.errors.SqlglotError,
        ValueError,
        jsonschema.exceptions.ValidationError,
        OSError,
        RecursionError,
    ) as e:
        # SqlglotError/ValueError: bad SQL, an unknown --dialect, or
        # multi-statement input -- genuine user-input problems.
        # ValidationError: tag_operations() itself produced a schema-invalid
        # shape (e.g. a join kind gdt's schema has no enum value for) -- an
        # internal limitation, but still something a CLI user hits as "this
        # query didn't tag," not a Python traceback.
        # OSError (covers PermissionError/FileNotFoundError/UnicodeDecodeError,
        # which subclasses ValueError but is listed here for clarity):
        # reading the input failed. RecursionError: sqlglot's own parser
        # exhausts Python's call stack on sufficiently deep nesting (real,
        # if unusual, generated SQL) -- not this package's own recursion, but
        # a CLI user still deserves a clean message instead of a stack dump.
        print(f"madflow-sqlops: {e}", file=sys.stderr)
        return 1

    indent = 2 if args.pretty else None
    print(json.dumps(result.to_dict(), indent=indent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
