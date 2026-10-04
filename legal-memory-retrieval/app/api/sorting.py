"""Whitelisted ORDER BY for list endpoints (the caller names a column; SQL never sees the raw text)."""
from __future__ import annotations


def order_by(sort: str | None, direction: str | None, columns: dict[str, str], default: str, tiebreak: str) -> str:
    """``ORDER BY`` clause for ``sort`` (a key of ``columns``) in ``direction`` ("asc" or "desc").

    Unknown keys fall back to ``default``. Missing values always sort last, and ``tiebreak`` keeps pages stable.
    """
    key = sort if sort in columns else default
    way = "ASC" if (direction or "").lower() == "asc" else "DESC"
    return f"ORDER BY {columns[key]} {way} NULLS LAST, {tiebreak} {way}"
