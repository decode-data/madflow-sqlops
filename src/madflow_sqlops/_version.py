"""Pinned GDT spec version this package tags against.

Bumping either constant requires re-vendoring src/madflow_sqlops/_schema/
and re-running the golden-file test suite against the new schema.
"""

GDT_TAG = "v0.2.0"
"""Git tag in https://github.com/decode-data/gdt this package is pinned to."""

GDT_SCHEMA_VERSION = "0.2"
"""Value of the schema's `gdt_version` const — emitted verbatim in every tagged result."""
