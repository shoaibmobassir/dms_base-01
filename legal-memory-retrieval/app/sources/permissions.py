"""ACL helpers for source files (Phase 0: matter-trust; store ACLs for later)."""
from __future__ import annotations

from app.sources.models import Permission


def matter_trust_allows(*, matter_acl_ok: bool) -> bool:
    """Phase 0: searchable iff firm matter ACL already allows the member."""
    return matter_acl_ok


def principal_intersects(
    permissions: list[Permission],
    *,
    member_id: str | None,
    mapped_provider_ids: set[str],
) -> bool:
    """Strict mode helper (Phase A+): member matches a mapped principal."""
    if not member_id:
        return False
    for p in permissions:
        if p.principal_type == "anyone":
            return True
        if p.principal_type == "user" and (
            p.principal_id in mapped_provider_ids or p.principal_id == member_id
        ):
            return True
    return False
