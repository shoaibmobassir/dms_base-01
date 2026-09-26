# `permissions` is compiled from the access model (migration 20260927a): screens
# (denied_members) win over firm-open matters and over allow-list grants.
ACL_CLAUSE = (
    "(%(member_id)s::text IS NULL"
    " OR ((p.restricted = FALSE OR %(member_id)s::text = ANY(p.allowed_members))"
    " AND NOT (%(member_id)s::text = ANY(p.denied_members))))"
)


def acl_epoch() -> str:
    """Changes whenever any matter's compiled ACL changes (grant, screen, mode, team).

    Part of every retrieval cache key, so a result cached before a screen or a
    revoked grant is never served after it. Backed by an index on compiled_at.
    """
    from app.db.connection import connect

    try:
        with connect() as conn:
            row = conn.execute("SELECT max(compiled_at) AS epoch FROM permissions").fetchone()
        value = row["epoch"] if isinstance(row, dict) else row[0]
        return value.isoformat() if value else "0"
    except Exception:
        return "unavailable"
