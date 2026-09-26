"""Resolve what an Ask-the-Firm question is scoped to.

Three inputs are accepted, in priority order:
  1. an explicit structured scope from the UI ({"type": "matter"|"client", "value": ...});
  2. a legacy "<scope>: <question>" prefix (older UI builds and bookmarks);
  3. a matter code or matter id written inside the question.

Every lookup applies the ethical-wall ACL in SQL, so a restricted matter the
member cannot see never resolves.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

ACL_SQL = """
    (%(member_id)s::text IS NULL
     OR ((p.restricted = FALSE OR %(member_id)s::text = ANY (p.allowed_members))
         AND NOT (%(member_id)s::text = ANY (p.denied_members))))
"""

_MATTER_COLS = """
    m.matter_id, m.matter_code, m.title, cl.name AS client_name, m.opposing_party,
    m.practice_area, m.status, m.jurisdiction, m.court
"""

# Matter ids and codes as they appear in this DMS: MTR-2026-00901,
# CORP/BLR/0901/2026, PIL/HAG/0005/1925, CI-OPEN-001.
_CODE_TOKEN_RE = re.compile(
    r"\bMTR-\d{4}-\d+\b|\b[A-Z]{2,6}(?:/[A-Z0-9]{2,8}){2,4}\b|\b[A-Z]{2,6}-[A-Z]{2,8}-\d{2,5}\b",
    re.I,
)
_PREFIX_RE = re.compile(r"^\s*([^:?\n]{2,120}?)\s*:\s+(\S.*)$", re.S)


@dataclass
class MatterRef:
    matter_id: str
    matter_code: str
    title: str
    client_name: str | None = None
    opposing_party: str | None = None
    practice_area: str | None = None
    status: str | None = None
    jurisdiction: str | None = None
    court: str | None = None
    method: str = ""
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScopeResolution:
    question: str
    kind: str = "none"  # matter | client | none
    label: str = ""
    method: str = ""
    requested: dict[str, str] | None = None
    matters: list[MatterRef] = field(default_factory=list)
    unresolved: bool = False  # a scope was requested but matched nothing accessible

    @property
    def matter_ids(self) -> list[str]:
        return [m.matter_id for m in self.matters]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "method": self.method,
            "requested": self.requested,
            "unresolved": self.unresolved,
            "matter_ids": self.matter_ids,
            "matters": [m.to_dict() for m in self.matters],
        }


def _fetch(conn, sql: str, params: dict[str, Any]) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [c.name for c in cur.description]
        return [r if isinstance(r, dict) else dict(zip(cols, r)) for r in cur.fetchall()]


def _refs(rows: list[dict], method: str) -> list[MatterRef]:
    fields = MatterRef.__dataclass_fields__
    out = []
    for r in rows:
        data = {k: r.get(k) for k in fields if k in r}
        data["method"] = method
        data["score"] = float(r.get("score") or 0.0)
        out.append(MatterRef(**data))
    return out


def matters_by_ids_or_codes(conn, tokens: list[str], member_id: str | None) -> list[MatterRef]:
    wanted = [t.strip().upper() for t in tokens if t and t.strip()]
    if not wanted:
        return []
    rows = _fetch(
        conn,
        f"""
        SELECT {_MATTER_COLS}
        FROM matters m
        JOIN clients cl ON cl.client_id = m.client_id
        JOIN permissions p ON p.matter_id = m.matter_id
        WHERE {ACL_SQL}
          AND (upper(m.matter_id) = ANY(%(wanted)s) OR upper(m.matter_code) = ANY(%(wanted)s))
        ORDER BY m.matter_id
        """,
        {"member_id": member_id, "wanted": wanted},
    )
    return _refs(rows, "code")


def matters_by_title(conn, text: str, member_id: str | None, limit: int = 5) -> list[MatterRef]:
    """Exact / prefix / trigram title match, best first."""
    needle = (text or "").strip()
    if len(needle) < 3:
        return []
    rows = _fetch(
        conn,
        f"""
        SELECT {_MATTER_COLS},
               CASE WHEN lower(m.title) = lower(%(n)s) THEN 1.0
                    WHEN m.title ILIKE %(n)s || '%%' THEN 0.9
                    ELSE similarity(lower(m.title), lower(%(n)s)) END AS score
        FROM matters m
        JOIN clients cl ON cl.client_id = m.client_id
        JOIN permissions p ON p.matter_id = m.matter_id
        WHERE {ACL_SQL}
          AND (m.title ILIKE %(n)s || '%%' OR similarity(lower(m.title), lower(%(n)s)) >= 0.45)
        ORDER BY score DESC, m.matter_id
        LIMIT %(limit)s
        """,
        {"member_id": member_id, "n": needle, "limit": limit},
    )
    return _refs(rows, "title")


def matters_for_client(
    conn, text: str, member_id: str | None, limit: int = 50, min_score: float = 0.5,
) -> tuple[list[MatterRef], str]:
    """All accessible matters for the client whose name/alias best matches ``text``."""
    needle = (text or "").strip()
    if len(needle) < 2:
        return [], ""
    clients = _fetch(
        conn,
        """
        SELECT client_id, name,
               CASE WHEN lower(name) = lower(%(n)s) OR lower(%(n)s) = ANY(SELECT lower(a) FROM unnest(aliases) a) THEN 1.0
                    WHEN name ILIKE %(n)s || '%%' THEN 0.9
                    WHEN name ILIKE '%%' || %(n)s || '%%' THEN 0.8
                    ELSE similarity(lower(name), lower(%(n)s)) END AS score
        FROM clients
        WHERE lower(name) = lower(%(n)s)
           OR lower(%(n)s) = ANY(SELECT lower(a) FROM unnest(aliases) a)
           OR name ILIKE '%%' || %(n)s || '%%'
           OR similarity(lower(name), lower(%(n)s)) >= 0.5
        ORDER BY score DESC
        LIMIT 3
        """,
        {"n": needle},
    )
    if not clients or float(clients[0]["score"]) < min_score:
        return [], ""
    best = clients[0]
    ids = [c["client_id"] for c in clients if float(c["score"]) >= float(best["score"]) - 1e-9]
    rows = _fetch(
        conn,
        f"""
        SELECT {_MATTER_COLS}, 1.0 AS score
        FROM matters m
        JOIN clients cl ON cl.client_id = m.client_id
        JOIN permissions p ON p.matter_id = m.matter_id
        WHERE {ACL_SQL} AND m.client_id = ANY(%(ids)s)
        ORDER BY m.opened_date DESC NULLS LAST, m.matter_id
        LIMIT %(limit)s
        """,
        {"member_id": member_id, "ids": ids, "limit": limit},
    )
    return _refs(rows, "client"), str(best["name"])


def resolve_scope_value(
    conn, kind: str, value: str, member_id: str | None, *, strict: bool = False,
) -> ScopeResolution:
    """Resolve a scope string. ``strict`` (used for un-typed "X: question"
    prefixes) only accepts exact codes, near-exact titles and clear client
    names, so "Note: ..." never scopes to a client that contains "note".
    """
    kind = (kind or "").strip().lower()
    kind = "" if kind == "auto" else kind
    value = (value or "").strip()
    res = ScopeResolution(question="", requested={"type": kind, "value": value}, label=value)
    if not value:
        return res
    if kind in {"matter", ""}:
        found = matters_by_ids_or_codes(conn, [value], member_id)
        if not found:
            found = matters_by_title(conn, value, member_id, limit=1)
            if strict:
                found = [m for m in found if m.score >= 0.9]
        if found:
            res.kind, res.matters, res.method = "matter", found[:1], found[0].method
            res.label = found[0].matter_code
            return res
        if kind == "matter":
            res.unresolved = True
            return res
    found, client = matters_for_client(conn, value, member_id, min_score=0.8 if strict else 0.5)
    if found:
        res.kind, res.matters, res.method, res.label = "client", found, "client", client
    else:
        res.unresolved = True
    return res


def resolve_scope(
    conn,
    question: str,
    scope: dict[str, str] | None,
    member_id: str | None,
) -> ScopeResolution:
    text = (question or "").strip()
    if scope and (scope.get("value") or "").strip():
        res = resolve_scope_value(conn, scope.get("type") or "", scope.get("value") or "", member_id)
        res.question = text
        return res

    prefix = _PREFIX_RE.match(text)
    if prefix:
        head, rest = prefix.group(1).strip(), prefix.group(2).strip()
        res = resolve_scope_value(conn, "", head, member_id, strict=True)
        if res.matters:
            res.question = rest
            res.method = f"prefix_{res.method}"
            return res

    tokens = _CODE_TOKEN_RE.findall(text)
    if tokens:
        found = matters_by_ids_or_codes(conn, tokens, member_id)
        if found:
            return ScopeResolution(
                question=text, kind="matter", matters=found, method="inline_code",
                label=", ".join(m.matter_code for m in found),
            )
    return ScopeResolution(question=text)


def client_named_in(conn, text: str, member_id: str | None) -> tuple[list[MatterRef], str]:
    """Matters of the client whose full name or alias appears verbatim in ``text``."""
    t = (text or "").strip()
    if len(t) < 4:
        return [], ""
    rows = _fetch(
        conn,
        """
        SELECT name FROM clients
        WHERE (char_length(name) >= 4 AND position(lower(name) in lower(%(t)s)) > 0)
           OR EXISTS (SELECT 1 FROM unnest(aliases) a
                      WHERE char_length(a) >= 4 AND position(lower(a) in lower(%(t)s)) > 0)
        ORDER BY char_length(name) DESC
        LIMIT 1
        """,
        {"t": t},
    )
    if not rows:
        return [], ""
    return matters_for_client(conn, rows[0]["name"], member_id, min_score=0.8)
