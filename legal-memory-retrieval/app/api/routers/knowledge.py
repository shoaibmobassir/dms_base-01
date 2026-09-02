from fastapi import APIRouter, Query
from psycopg.rows import dict_row

from app.db.connection import connect

router = APIRouter(tags=["knowledge"])

SERVICE = "knowledge"


@router.get("/health")
def knowledge_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.get("/arguments")
def knowledge_arguments(
    q: str | None = Query(default=None),
    limit: int = Query(default=30, le=100),
) -> dict:
    params: dict = {"limit": limit}
    if q:
        params["like"] = f"%{q}%"
        sql = """
            SELECT a.argument_id, a.matter_id, a.issue, a.position, a.argument,
                   a.outcome, m.matter_code, m.practice_area, m.title AS matter_title
            FROM arguments a
            JOIN matters m ON m.matter_id = a.matter_id
            WHERE a.issue ILIKE %(like)s OR a.argument ILIKE %(like)s
               OR a.position ILIKE %(like)s
            ORDER BY a.issue
            LIMIT %(limit)s
        """
    else:
        sql = """
            SELECT a.argument_id, a.matter_id, a.issue, a.position, a.argument,
                   a.outcome, m.matter_code, m.practice_area, m.title AS matter_title
            FROM arguments a
            JOIN matters m ON m.matter_id = a.matter_id
            ORDER BY a.argument_id
            LIMIT %(limit)s
        """
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            items = list(cur.fetchall())
            cur.execute("SELECT COUNT(*) AS n FROM arguments")
            total = cur.fetchone()["n"]
    return {"service": SERVICE, "total": total, "items": items}


@router.get("/precedents")
def knowledge_precedents() -> dict:
    return {
        "service": SERVICE,
        "precedents": [
            {
                "id": "PREC-001",
                "title": "Master Share Purchase Agreement (Locked-Box & W&I)",
                "type": "M&A Contract",
                "rating": 4.9,
                "usage": "38 matters",
                "summary": "Firm-wide gold standard SPA with locked-box value mechanisms, anti-leakage indemnity, and W&I insurance integration.",
                "author": "Aryan Maharaj",
                "office": "Mumbai",
            },
            {
                "id": "PREC-002",
                "title": "Company Petition u/s 241-242 (Oppression & Mismanagement)",
                "type": "NCLT Pleading",
                "rating": 4.8,
                "usage": "24 matters",
                "summary": "Tested pleading template establishing promoter siphoning, board exclusion, and urgent ad-interim restraining orders.",
                "author": "Udant Dewan",
                "office": "Delhi",
            },
            {
                "id": "PREC-003",
                "title": "SIAC Notice of Arbitration & Emergency Injunction Application",
                "type": "Arbitration Notice",
                "rating": 4.9,
                "usage": "19 matters",
                "summary": "Bespoke SIAC 2024 expedited emergency arbitrator application for cross-border JV disputes and asset freezing.",
                "author": "Aryan Maharaj",
                "office": "Singapore",
            },
        ],
    }


@router.get("/clauses")
def knowledge_clauses() -> dict:
    return {
        "service": SERVICE,
        "clauses": [
            {
                "id": "CLS-IND-01",
                "title": "Indemnity Cap & De Minimis Threshold",
                "category": "Liability & Risk",
                "success_rate": "92% Enforceability",
                "standard_text": "The aggregate maximum liability of the Seller in respect of Warranty Claims shall not exceed 15% of the Purchase Price, save and except in the case of Fundamental Warranties and Tax Claims.",
                "fallback_pro_buyer": "Fundamental warranties and fraud claims uncapped; general warranty cap set at 25% of purchase price with 24-month survival period.",
                "fallback_pro_seller": "All warranty and tax claims strictly capped at 10% of purchase price with 12-month survival and de minimis tipping threshold.",
            },
            {
                "id": "CLS-LKB-02",
                "title": "Locked-Box Anti-Leakage Undertaking",
                "category": "M&A Structuring",
                "success_rate": "96% Acceptance",
                "standard_text": "The Seller covenants that between the Locked-Box Date and Closing Date, no Leakage has occurred or shall occur in relation to the Target Company.",
                "fallback_pro_buyer": "Seller indemnifies on a rupee-for-rupee basis on gross tax basis for any unauthorized extraction or intra-group loan waiver.",
                "fallback_pro_seller": "Permitted leakage explicitly includes ordinary-course director remuneration and approved pre-closing bonuses.",
            },
        ],
    }
