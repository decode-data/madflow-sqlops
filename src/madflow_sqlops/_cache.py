"""Cache-key computation (README -> Architecture, step 3).

Persistence is the caller's concern; this module only computes the key.
"""

from __future__ import annotations

import hashlib


def cache_key(sql: str, dialect: str) -> str:
    """Deterministic key for a (sql, dialect) pair -- identical input hits the cache."""
    return hashlib.sha256(f"{dialect}:{sql}".encode("utf-8")).hexdigest()
