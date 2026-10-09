from fastapi import APIRouter, Depends, Query
from psycopg.rows import dict_row

from app.api.acl import ACL_CLAUSE, doc_acl
from app.auth.deps import resolve_member
from app.db.connection import connect

router = APIRouter(tags=["search"])

SERVICE = "search"

KINDS = ("matter", "document", "client", "member")
# Share of the result list each kind is guaranteed when it has hits. Slots a kind does not use
# go to the others, documents first (the old code cut the list after matters, so 20 matching
# matters meant no documents at all).
QUOTA = {"matter": 5, "document": 8, "client": 3, "member": 4}
FILL_ORDER = ("document", "matter", "client", "member")
MARK_START, MARK_END = "<<", ">>"


@router.get("/health")
def search_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


def _quotas(limit: int, present: list[str]) -> dict[str, int]:
    total = sum(QUOTA[k] for k in present) or 1
    return {k: max(1, round(limit * QUOTA[k] / total)) for k in present}


def _combine(by_kind: dict[str, list[dict]], limit: int) -> list[dict]:
    """Guarantee each kind its share, then fill the remaining slots from whatever is left."""
    present = [k for k in KINDS if by_kind.get(k)]
    if not present:
        return []
    quotas = _quotas(limit, present)
    taken = {k: by_kind[k][: quotas[k]] for k in present}
    room = limit - sum(len(v) for v in taken.values())
    for k in FILL_ORDER:
        if room <= 0:
            break
        extra = by_kind.get(k, [])[len(taken.get(k, [])): len(taken.get(k, [])) + room]
        if extra:
            taken[k] = taken.get(k, []) + extra
            room -= len(extra)
    return [row for k in KINDS for row in taken.get(k, [])][:limit]


@router.get("")
def search(
    q: str,
    kind: str = Query(default="all", description="all|matter|document|client|member"),
    member_id: str | None = Depends(resolve_member),
    limit: int = Query(default=20, le=50),
) -> dict:
    q = q.strip()
    if not q:
        return {"service": SERVICE, "query": q, "results": []}
    like = f"%{q}%"
    fetch = limit  # any one kind may need every slot when the others have no hits
    by_kind: dict[str, list[dict]] = {}
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if kind in ("all", "matter"):
                cur.execute(
                    f"""
                    SELECT 'matter' AS kind, m.matter_id AS id,
                           m.matter_code AS code, m.title,
                           m.client_name AS subtitle, m.practice_area AS meta,
                           m.status
                    FROM matters m
                    LEFT JOIN permissions p ON p.matter_id = m.matter_id
                    WHERE (m.title ILIKE %(like)s OR m.matter_code ILIKE %(like)s
                           OR m.client_name ILIKE %(like)s)
                      AND {ACL_CLAUSE}
                    ORDER BY m.opened_date DESC NULLS LAST
                    LIMIT %(limit)s
                    """,
                    {"like": like, "member_id": member_id, "limit": fetch},
                )
                by_kind["matter"] = cur.fetchall()
            if kind in ("all", "document"):
                # Title and type first, then words inside the document. Content is matched on the
                # indexed chunk text (chunks.tsv_full), the best chunk per document, and a short
                # highlighted snippet is returned so the user can see why it matched.
                cur.execute(
                    f"""
                    WITH q AS (SELECT websearch_to_tsquery('english', %(q)s) AS tq),
                    hits AS (
                        SELECT DISTINCT ON (c.document_id)
                               c.document_id, c.text, ts_rank_cd(c.tsv_full, q.tq) AS rank
                        FROM chunks c, q
                        WHERE c.tsv_full @@ q.tq AND NOT COALESCE(c.is_parent, false)
                        ORDER BY c.document_id, rank DESC
                    ),
                    cand AS (
                        SELECT d.document_id, d.title, d.document_type, d.matter_code, d.status, d.doc_date,
                               (d.title ILIKE %(like)s OR d.document_type ILIKE %(like)s) AS title_hit,
                               h.rank, h.text
                        FROM documents d
                        LEFT JOIN permissions p ON p.matter_id = d.matter_id
                        LEFT JOIN hits h ON h.document_id = d.document_id
                        WHERE (d.title ILIKE %(like)s OR d.document_type ILIKE %(like)s
                               OR h.document_id IS NOT NULL)
                          AND {ACL_CLAUSE} AND {doc_acl('d')}
                        ORDER BY title_hit DESC, h.rank DESC NULLS LAST, d.doc_date DESC NULLS LAST
                        LIMIT %(limit)s
                    )
                    SELECT 'document' AS kind, document_id AS id, document_id AS code, title,
                           document_type AS subtitle, matter_code AS meta, status,
                           CASE WHEN title_hit THEN 'title' ELSE 'content' END AS match_kind,
                           CASE WHEN text IS NULL THEN NULL ELSE ts_headline(
                               'english', text, (SELECT tq FROM q),
                               'StartSel={MARK_START}, StopSel={MARK_END}, MaxWords=26, MinWords=10, MaxFragments=1'
                           ) END AS snippet
                    FROM cand
                    ORDER BY title_hit DESC, rank DESC NULLS LAST, doc_date DESC NULLS LAST
                    """,
                    {"like": like, "q": q, "member_id": member_id, "limit": fetch},
                )
                by_kind["document"] = cur.fetchall()
            if kind in ("all", "client"):
                cur.execute(
                    "SELECT 'client' AS kind, client_id AS id, client_id AS code,"
                    " name AS title, industry AS subtitle, headquarters AS meta,"
                    " NULL AS status"
                    " FROM clients WHERE name ILIKE %(like)s OR industry ILIKE %(like)s"
                    " LIMIT %(limit)s",
                    {"like": like, "limit": fetch},
                )
                by_kind["client"] = cur.fetchall()
            if kind in ("all", "member"):
                cur.execute(
                    "SELECT 'member' AS kind, member_id AS id, member_id AS code,"
                    " name AS title, role AS subtitle, office AS meta, NULL AS status"
                    " FROM members WHERE name ILIKE %(like)s OR role ILIKE %(like)s"
                    " LIMIT %(limit)s",
                    {"like": like, "limit": fetch},
                )
                by_kind["member"] = cur.fetchall()
    return {"service": SERVICE, "query": q, "results": _combine(by_kind, limit)}
