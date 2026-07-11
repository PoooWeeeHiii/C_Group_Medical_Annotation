"""Helpers to generate the unified ``<Entity>%04d`` identifiers (docs/01)."""
from __future__ import annotations

import re

from sqlalchemy import func
from sqlalchemy.orm import Session


def _next_number(db: Session, column, prefix: str) -> int:
    """Return the next sequential number for a given id column/prefix.

    Parses the numeric suffix of existing ids and returns max + 1 so deletions
    never cause a collision.
    """
    rows = db.query(column).all()
    max_n = 0
    pat = re.compile(rf"^{prefix}(\d+)$")
    for (value,) in rows:
        if not value:
            continue
        m = pat.match(value)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def next_id(db: Session, column, prefix: str) -> str:
    """e.g. next_id(db, Case.case_id, "Case") -> 'Case0001'."""
    return f"{prefix}{_next_number(db, column, prefix):04d}"
