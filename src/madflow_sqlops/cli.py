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

import sqlglot.errors

from .tagging import tag_operations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="madflow-sqlops")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tag_parser = subparsers.add_parser("tag", help="Tag a SQL file's operations against GDT")
    tag_parser.add_argument("file", help="Path to a .sql file, or '-' to read from stdin")
    tag_parser.add_argument("--dialect", required=True, help="sqlglot dialect, e.g. snowflake, bigquery, duckdb")
    tag_parser.add_argument("--pretty", action="store_true", help="Indent the JSON output for human reading")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.file == "-":
        sql = sys.stdin.read()
    else:
        path = Path(args.file)
        if not path.is_file():
            print(f"madflow-sqlops: no such file: {args.file}", file=sys.stderr)
            return 1
        sql = path.read_text()

    try:
        result = tag_operations(sql, dialect=args.dialect)
    except (sqlglot.errors.SqlglotError, ValueError) as e:
        print(f"madflow-sqlops: {e}", file=sys.stderr)
        return 1

    indent = 2 if args.pretty else None
    print(json.dumps(result.to_dict(), indent=indent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
