#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from app.config import settings
from app.db.chunking import chunk_text
from app.db.connection import connect


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def main() -> None:
    corpus = Path(settings.corpus_dir)
    if not corpus.is_absolute():
        corpus = (ROOT / corpus).resolve()
    schema = (ROOT / "app" / "db" / "schema.sql").read_text(encoding="utf-8")

    members = load_json(corpus / "members.json")
    clients = load_json(corpus / "clients.json")
    matters = load_json(corpus / "matters.json")
    permissions = load_json(corpus / "permissions.json")

    with connect() as conn:
        _apply_schema(conn, schema)
        _insert_members(conn, members)
        _insert_clients(conn, clients)
        _insert_matters(conn, matters)
        _insert_permissions(conn, permissions)
        n_docs, n_chunks = _insert_documents(conn, corpus / "documents.jsonl")
        n_rel = _insert_relationships(conn, corpus / "relationships.jsonl")
        n_args = _insert_arguments(conn, corpus / "arguments.jsonl")
        conn.commit()

    print(
        json.dumps(
            {
                "members": len(members),
                "clients": len(clients),
                "matters": len(matters),
                "documents": n_docs,
                "chunks": n_chunks,
                "relationships": n_rel,
                "arguments": n_args,
            },
            indent=2,
        )
    )


def _apply_schema(conn, schema: str) -> None:
    for stmt in schema.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)


def _insert_members(conn, rows) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO members (
                member_id, name, role, practice_areas, specializations,
                office, joined_year, email, is_lawyer
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    r["member_id"],
                    r["name"],
                    r["role"],
                    r.get("practice_areas") or [],
                    r.get("specializations") or [],
                    r.get("office"),
                    r.get("joined_year"),
                    r.get("email"),
                    r.get("is_lawyer", True),
                )
                for r in rows
            ],
        )


def _insert_clients(conn, rows) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO clients (
                client_id, name, industry, size, headquarters, locations,
                subsidiaries, preferred_lawyer_ids, aliases
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    r["client_id"],
                    r["name"],
                    r.get("industry"),
                    r.get("size"),
                    r.get("headquarters"),
                    r.get("locations") or [],
                    r.get("subsidiaries") or [],
                    r.get("preferred_lawyer_ids") or [],
                    r.get("aliases") or [],
                )
                for r in rows
            ],
        )


def _insert_matters(conn, rows) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO matters (
                matter_id, matter_code, title, client_id, client_name, opposing_party,
                practice_area, matter_type, theme_key, jurisdiction, court,
                opened_date, closed_date, status, office, claim_amount, outcome,
                legal_issues, facts
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            [
                (
                    r["matter_id"],
                    r["matter_code"],
                    r["title"],
                    r["client_id"],
                    r.get("client_name"),
                    r.get("opposing_party"),
                    r["practice_area"],
                    r["matter_type"],
                    r.get("theme_key"),
                    r.get("jurisdiction"),
                    r.get("court"),
                    r.get("opened_date"),
                    r.get("closed_date"),
                    r.get("status"),
                    r.get("office"),
                    r.get("claim_amount"),
                    r.get("outcome"),
                    r.get("legal_issues") or [],
                    r.get("facts") or [],
                )
                for r in rows
            ],
        )
        mm = []
        for r in rows:
            for item in r.get("matter_members") or []:
                mm.append((r["matter_id"], item["member_id"], item.get("role_on_matter")))
        cur.executemany(
            """
            INSERT INTO matter_members (matter_id, member_id, role_on_matter)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            mm,
        )


def _insert_permissions(conn, rows) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO permissions (matter_id, classification, restricted, allowed_members, practice_area)
            VALUES (%s, %s, %s, %s, %s)
            """,
            [
                (
                    r["matter_id"],
                    r.get("classification"),
                    r.get("restricted", False),
                    r.get("allowed_members") or [],
                    r.get("practice_area"),
                )
                for r in rows
            ],
        )


def _insert_documents(conn, path: Path) -> tuple[int, int]:
    n_docs = 0
    n_chunks = 0
    batch_docs: list[tuple] = []
    batch_chunks: list[tuple] = []
    with conn.cursor() as cur:
        for doc in iter_jsonl(path):
            n_docs += 1
            batch_docs.append(
                (
                    doc["document_id"],
                    doc["matter_id"],
                    doc.get("matter_code"),
                    doc.get("client_id"),
                    doc["title"],
                    doc["document_type"],
                    doc.get("author_id"),
                    doc.get("author_name"),
                    doc.get("date"),
                    doc.get("status"),
                    doc.get("version"),
                    doc.get("parent_document_id"),
                    doc.get("version_group"),
                    doc.get("text") or "",
                )
            )
            for idx, piece in enumerate(chunk_text(doc.get("text") or "")):
                n_chunks += 1
                chunk_id = f"{doc['document_id']}-C{idx:03d}"
                batch_chunks.append((chunk_id, doc["document_id"], doc["matter_id"], idx, piece))
            if len(batch_docs) >= 500:
                _flush_docs(cur, batch_docs, batch_chunks)
                batch_docs, batch_chunks = [], []
                print(f"ingested documents={n_docs} chunks={n_chunks}", flush=True)
        if batch_docs:
            _flush_docs(cur, batch_docs, batch_chunks)
    return n_docs, n_chunks


def _flush_docs(cur, docs: list[tuple], chunks: list[tuple]) -> None:
    cur.executemany(
        """
        INSERT INTO documents (
            document_id, matter_id, matter_code, client_id, title, document_type,
            author_id, author_name, doc_date, status, version, parent_document_id,
            version_group, body
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        docs,
    )
    cur.executemany(
        """
        INSERT INTO chunks (chunk_id, document_id, matter_id, chunk_index, text, tsv)
        VALUES (%s, %s, %s, %s, %s, to_tsvector('english', %s))
        """,
        [(c[0], c[1], c[2], c[3], c[4], c[4]) for c in chunks],
    )


def _insert_relationships(conn, path: Path) -> int:
    rows = [(r["source"], r["type"], r["target"]) for r in iter_jsonl(path)]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO relationships (source_id, rel_type, target_id) VALUES (%s, %s, %s)",
            rows,
        )
    return len(rows)


def _insert_arguments(conn, path: Path) -> int:
    rows = []
    for r in iter_jsonl(path):
        rows.append(
            (
                r["argument_id"],
                r["matter_id"],
                r.get("issue"),
                r.get("position"),
                r.get("argument"),
                r.get("outcome"),
                r.get("supporting_documents") or [],
            )
        )
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO arguments (
                argument_id, matter_id, issue, position, argument, outcome, supporting_documents
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )
    return len(rows)


if __name__ == "__main__":
    main()
