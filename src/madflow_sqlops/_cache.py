"""Cache-key computation (README -> Architecture, step 3).

Persistence is the caller's concern; this module only computes the key.
"""

from __future__ import annotations

import hashlib


def cache_key(sql: str, dialect: str) -> str:
    """Deterministic key for a (sql, dialect) pair -- identical input hits the cache.

    Length-prefixes `dialect` before combining with `sql` so the boundary
    between them is unambiguous regardless of what characters either string
    contains -- a bare "dialect:sql" separator would let cache_key("b:c", "a")
    and cache_key("c", "a:b") collide (both join to "a:b:c").
    """
    return hashlib.sha256(f"{len(dialect)}:{dialect}:{sql}".encode("utf-8")).hexdigest()
