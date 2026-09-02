ACL_CLAUSE = (
    "(%(member_id)s::text IS NULL"
    " OR p.restricted = FALSE"
    " OR %(member_id)s::text = ANY(p.allowed_members))"
)
