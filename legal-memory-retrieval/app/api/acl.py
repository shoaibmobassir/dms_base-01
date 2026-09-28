# `permissions` is compiled from the access model (migration 20260927a): screens
# (denied_members) win over firm-open matters and over allow-list grants.
ACL_CLAUSE = (
    "(%(member_id)s::text IS NULL"
    " OR ((p.restricted = FALSE OR %(member_id)s::text = ANY(p.allowed_members))"
    " AND NOT (%(member_id)s::text = ANY(p.denied_members))))"
)




def doc_acl(alias: str = "d") -> str:
    """Document-level privacy (migration 20260928c), for a ``documents`` or ``chunks`` alias.

    A private or restricted document is visible only to the members compiled into its
    ``visible_to``; NULL means it follows its matter. Always used *with* the matter clause
    (``ACL_CLAUSE``): document privacy narrows matter access, it never widens it.
    """
    return (f"(%(member_id)s::text IS NULL OR {alias}.visible_to IS NULL"
            f" OR %(member_id)s::text = ANY({alias}.visible_to))")


def acl_epoch() -> str:
    """Changes whenever any compiled ACL changes: a matter's (grant, screen, mode, team,
    staffing) or a document's (privacy, shares).

    Part of every retrieval cache key, so a result cached before a screen, a revoked grant
    or a document made private is never served after it. Backed by an index on compiled_at.
    """
    from app.db.connection import connect

    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT (SELECT max(compiled_at) FROM permissions) AS epoch,"
                " (SELECT max(changed_at) FROM doc_acl_state) AS doc_epoch").fetchone()
        value = row["epoch"] if isinstance(row, dict) else row[0]
        doc_value = row["doc_epoch"] if isinstance(row, dict) else row[1]
        return f"{value.isoformat() if value else '0'}|{doc_value.isoformat() if doc_value else '0'}"
    except Exception:
        return "unavailable"
