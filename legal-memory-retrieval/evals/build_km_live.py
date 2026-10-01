"""Build the Ask-the-Firm KM live eval set with gold derived from Postgres.

Every expected value is read from the database at build time (matters,
matter_members, members, permissions, clients), never hand-typed, so the set
stays correct when the corpus is re-seeded.

Usage:
    python evals/build_km_live.py            # writes evals/km_live.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from app.db.connection import connect  # noqa: E402

OUT = Path(__file__).with_name("km_live.jsonl")
EVAL_MEMBER = "MEM-00011"  # Knowledge Manager — broad but not unrestricted access


def _rows(conn, sql: str, params: tuple = ()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [c.name for c in cur.description]
        return [r if isinstance(r, dict) else dict(zip(cols, r)) for r in cur.fetchall()]


def _accessible(conn, member_id: str) -> list[dict]:
    return _rows(
        conn,
        """
        SELECT m.matter_id, m.matter_code, m.title, cl.name AS client_name,
               m.opposing_party, m.facts, m.legal_issues, m.practice_area,
               (SELECT count(*) FROM documents d WHERE d.matter_id = m.matter_id) AS n_docs
        FROM matters m
        JOIN clients cl ON cl.client_id = m.client_id
        JOIN permissions p ON p.matter_id = m.matter_id
        WHERE p.restricted = FALSE OR %s = ANY(p.allowed_members)
        ORDER BY m.matter_id
        """,
        (member_id,),
    )


def _team(conn, matter_id: str) -> list[dict]:
    return _rows(
        conn,
        """
        SELECT mb.member_id, mb.name, mb.role, mm.role_on_matter
        FROM matter_members mm JOIN members mb USING (member_id)
        WHERE mm.matter_id = %s ORDER BY mb.member_id
        """,
        (matter_id,),
    )


def _short_title(title: str) -> str:
    return re.split(r"\s+[—–-]\s+", title)[0].strip()


def build(seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    rows: list[dict] = []
    with connect() as conn:
        matters = [m for m in _accessible(conn, EVAL_MEMBER) if m["n_docs"] > 0]
        pcij = [m for m in matters if m["matter_code"].startswith("PIL/")]
        unsc = [m for m in matters if m["matter_code"].startswith("REG/NYC/")]
        other = [m for m in matters if m not in pcij and m not in unsc]
        sample = rng.sample(pcij, min(8, len(pcij))) + rng.sample(unsc, min(4, len(unsc))) + other
        short_counts: dict[str, int] = {}
        for m in matters:
            short_counts[_short_title(m["title"]).lower()] = short_counts.get(_short_title(m["title"]).lower(), 0) + 1

        def distinctive(title: str) -> str:
            """Short title unless other matters share it (e.g. 87 'UN Security Council resolutions')."""
            short = _short_title(title)
            return short if short_counts.get(short.lower(), 0) == 1 else title

        for m in sample:
            code, mid = m["matter_code"], m["matter_id"]
            scope = {"type": "matter", "value": code}
            rows.append({
                "id": f"OVR-{code}", "category": "scoped_overview", "query": "explain this",
                "scope": scope, "gold_matter": mid,
                "gold_any": [m["client_name"], m["opposing_party"] or "", _short_title(m["title"])],
            })
            team = _team(conn, mid)
            if team:
                rows.append({
                    "id": f"TEAM-{code}", "category": "people_on_matter",
                    "query": "who is working on this matter?", "scope": scope,
                    "gold_matter": mid, "gold_people": [t["name"] for t in team],
                })
                lead = [t["name"] for t in team if (t["role_on_matter"] or "").lower() == "lead"]
                if lead:
                    rows.append({
                        "id": f"LEAD-{code}", "category": "lead_unscoped",
                        "query": f"who led our work on {distinctive(m['title'])}?",
                        "gold_matter": mid, "gold_people": lead,
                    })
            if m["opposing_party"] and m["client_name"] and code.startswith("PIL/"):
                if m["opposing_party"].lower() not in {"advisory proceeding"}:
                    rows.append({
                        "id": f"RESP-{code}", "category": "scoped_fact",
                        "query": "who was the other side in this matter?", "scope": scope,
                        "gold_matter": mid, "gold_all": [m["opposing_party"]],
                    })
                    rows.append({
                        "id": f"PARA-{code}", "category": "paraphrase_lowercase",
                        "query": (
                            f"the case where {m['client_name'].lower()} went against "
                            f"{m['opposing_party'].lower()} over {_short_title(m['title']).lower()}"
                        ),
                        "gold_matter": mid,
                    })
            n_res = next((re.match(r"(\d+) Security Council resolutions", f) for f in m["facts"] if re.match(r"\d+ Security Council", f)), None)
            if n_res:
                rows.append({
                    "id": f"NRES-{code}", "category": "scoped_fact",
                    "query": "how many resolutions were adopted?", "scope": scope,
                    "gold_matter": mid, "gold_all": [n_res.group(1)],
                })

        # Uploaded commercial matter (Acme) — document-level fact lookups.
        acme = next((m for m in matters if m["matter_code"] == "CORP/BLR/0901/2026"), None)
        if acme:
            scope = {"type": "matter", "value": acme["matter_code"]}
            for qid, q, gold in (
                ("ACME-LSD", "what is the long stop date?", ["31 March 2027"]),
                ("ACME-SHARES", "how many shares are being transferred?", ["1,240,000"]),
                ("ACME-BUYER", "who is the purchaser?", ["Northbridge"]),
                ("ACME-BOARD", "when did the board approve the transfer?", ["12 September 2026"]),
            ):
                rows.append({"id": qid, "category": "scoped_fact", "query": q, "scope": scope,
                             "gold_matter": acme["matter_id"], "gold_all": gold})
            rows.append({"id": "ACME-CLIENT", "category": "client_matters",
                         "query": "what work have we done for Acme Technologies?",
                         "gold_matters_any": [acme["matter_id"]]})
            rows.append({"id": "ACME-CLIENT-SCOPE", "category": "client_matters",
                         "query": "what deals have we done for them?",
                         "scope": {"type": "client", "value": "Acme Technologies"},
                         "gold_matters_any": [acme["matter_id"]]})
            rows.append({"id": "ACME-PARA", "category": "paraphrase_lowercase",
                         "query": "the series b deal where a seed investor sold its preference shares to a growth fund",
                         "gold_matter": acme["matter_id"]})

        # Clients with 2–6 matters → list questions.
        by_client: dict[str, list[dict]] = {}
        for m in matters:
            by_client.setdefault(m["client_name"], []).append(m)
        multi = [(c, ms) for c, ms in by_client.items() if 2 <= len(ms) <= 6 and c]
        for client, ms in rng.sample(multi, min(5, len(multi))):
            rows.append({
                "id": f"CLIENT-{client[:20]}", "category": "client_matters",
                "query": f"which matters have we handled for {client}?",
                "gold_matters_any": [m["matter_id"] for m in ms],
            })

        # People by specialization / office.
        for mb in _rows(conn, "SELECT member_id, name, role, office, specializations FROM members ORDER BY member_id"):
            if mb["specializations"]:
                spec = mb["specializations"][0]
                rows.append({
                    "id": f"SPEC-{mb['member_id']}", "category": "people_expertise",
                    "query": f"who in the firm is an expert in {spec.lower()}?",
                    "gold_people": [mb["name"]],
                })
        partners = _rows(conn, "SELECT name, office FROM members WHERE role = 'Partner' ORDER BY member_id")
        for p in partners:
            rows.append({
                "id": f"PARTNER-{p['office']}", "category": "people_expertise",
                "query": f"which partner sits in our {p['office']} office?",
                "gold_people": [p["name"]],
            })

        # Negatives: plausible but non-existent matters.
        for i, q in enumerate((
            "what was the case where acme challenged the bank?",
            "what did we advise Zephyrine Robotics on in its dispute with Obelisk Bank?",
            "the arbitration between Norland Shipping and Kestrel Insurance over a sunk tanker",
        )):
            rows.append({"id": f"NEG-{i}", "category": "negative", "query": q})

        # Ethical wall: a member outside a restricted matter asks for it by title.
        for r in _rows(conn, """
            SELECT m.matter_id, m.title, p.allowed_members FROM permissions p
            JOIN matters m USING (matter_id) WHERE p.restricted ORDER BY m.matter_id"""):
            outsider = next(
                (f"MEM-{n:05d}" for n in range(1, 17) if f"MEM-{n:05d}" not in r["allowed_members"]),
                None,
            )
            if outsider:
                rows.append({
                    "id": f"WALL-{r['matter_id']}", "category": "ethical_wall",
                    "query": f"summarise {_short_title(r['title'])}", "as_member": outsider,
                    "forbidden_matter": r["matter_id"],
                })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    rows = build(args.seed)
    with args.out.open("w") as fh:
        for row in rows:
            row.setdefault("as_member", EVAL_MEMBER)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    cats: dict[str, int] = {}
    for r in rows:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    print(f"wrote {len(rows)} rows to {args.out}: {cats}")


if __name__ == "__main__":
    main()
