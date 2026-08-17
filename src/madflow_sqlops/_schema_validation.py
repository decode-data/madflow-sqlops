"""Validate a tagged result against the vendored gdt JSON Schema.

README -> Architecture, step 4: fail loudly on drift rather than silently
emitting an unrecognized shape.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

import jsonschema

_SCHEMA_PACKAGE = "madflow_sqlops._schema"
_SCHEMA_FILENAME = "gdt-v0.1.schema.json"
"""Filename intentionally still says "v0.1" even though its content is gdt
v0.2 -- this is the real, current filename in the pinned ../gdt tag (v0.2.0),
not a mismatch introduced here. See src/madflow_sqlops/_version.py.
"""


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    schema_text = resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILENAME).read_text()
    return json.loads(schema_text)


def validate(document: dict[str, Any]) -> None:
    jsonschema.validate(instance=document, schema=load_schema())
