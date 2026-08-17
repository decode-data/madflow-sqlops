"""Public result types -- attribute-style access matching README's API sketch."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from ._categories import CATEGORY_NAMES, Operations as _OperationsDict


@dataclass(frozen=True)
class Operations:
    join: list[dict[str, Any]] = field(default_factory=list)
    filter: list[dict[str, Any]] = field(default_factory=list)
    set_op: list[dict[str, Any]] = field(default_factory=list)
    rename: list[dict[str, Any]] = field(default_factory=list)
    compute: list[dict[str, Any]] = field(default_factory=list)
    aggregate: list[dict[str, Any]] = field(default_factory=list)
    window: list[dict[str, Any]] = field(default_factory=list)
    cast: list[dict[str, Any]] = field(default_factory=list)
    conditional: list[dict[str, Any]] = field(default_factory=list)
    subquery_cte: list[dict[str, Any]] = field(default_factory=list)
    wildcard_select: list[dict[str, Any]] = field(default_factory=list)
    json_parse: list[dict[str, Any]] = field(default_factory=list)
    json_extract: list[dict[str, Any]] = field(default_factory=list)
    unnest: list[dict[str, Any]] = field(default_factory=list)
    ai_function: list[dict[str, Any]] = field(default_factory=list)
    udf: list[dict[str, Any]] = field(default_factory=list)
    column_hash: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, ops: _OperationsDict) -> Operations:
        return cls(**{name: ops[name] for name in CATEGORY_NAMES})

    def to_dict(self) -> _OperationsDict:
        # `frozen=True` only blocks reassigning an attribute -- it doesn't
        # stop a caller from mutating the list/dict *objects* an attribute
        # points at (a window entry's `frame` field is itself a nested dict).
        # Returning deep copies keeps "frozen" meaning what it looks like it
        # means: this result's internal state can't be corrupted by whatever
        # a caller does with the dict handed back, which matters for anyone
        # caching a TaggedResult (README frames caching as their concern).
        return {name: copy.deepcopy(getattr(self, name)) for name in CATEGORY_NAMES}


@dataclass(frozen=True)
class TaggedResult:
    gdt_version: str
    operations: Operations
    cache_key: str

    def to_dict(self) -> dict[str, Any]:
        return {"gdt_version": self.gdt_version, "operations": self.operations.to_dict()}
