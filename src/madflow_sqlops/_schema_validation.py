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
import jsonschema.validators

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


@lru_cache(maxsize=1)
def _validator() -> jsonschema.protocols.Validator:
    # jsonschema.validate() is a one-shot convenience wrapper: it re-derives
    # the validator class and re-checks the whole schema against its own
    # meta-schema on every call, even though the schema never changes here.
    # Building one Validator once (cached the same way load_schema() already
    # is) and reusing its .validate() avoids repeating that on every
    # tag_operations() call -- its own docstring recommends exactly this for
    # repeated validation against a fixed schema.
    schema = load_schema()
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    return validator_cls(schema)


def validate(document: dict[str, Any]) -> None:
    _validator().validate(document)
