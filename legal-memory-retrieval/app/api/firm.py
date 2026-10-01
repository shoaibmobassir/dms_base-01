"""Firm identity, read from the single-row ``firm_profile`` table."""
from __future__ import annotations

from psycopg.rows import dict_row

from app.config import settings


def firm_profile(conn) -> dict:
    """Return the firm profile, or a neutral placeholder before seeding."""
    with conn.cursor(row_factory=dict_row) as cur:
        try:
            cur.execute("SELECT name, descriptor, office, tenant_id FROM firm_profile LIMIT 1")
            row = cur.fetchone()
        except Exception:
            # Table missing (migrations not applied yet): don't fail the caller.
            conn.rollback()
            row = None
    return row or {
        "name": "Unconfigured firm",
        "descriptor": None,
        "office": None,
        "tenant_id": settings.tenant_id,
    }
