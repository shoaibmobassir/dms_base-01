#!/usr/bin/env python3
"""Seed the fictional "Acme Technologies — Series B Financing" matter as real files.

Documents are authored as DOCX and pushed through the same upload pipeline a lawyer's
files go through (object store → extraction → document → version → blocks → chunks →
embeddings). Nothing is inserted around the pipeline, so retrieval, citations and
versioning behave exactly as they will for real uploads.

All parties, people and terms are fictional.

Idempotent: the matter/team/deadlines are upserted; uploads are de-duplicated by
content hash; the SPA's second version is added only once.

Usage:
    python scripts/seed_acme.py              # after migrate.py (+ seed_demo.py)
    python scripts/seed_acme.py --anchor 2026-09-24
"""
from __future__ import annotations

import argparse
import io
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from docx import Document
from docx.shared import Pt

from app.db.connection import connect

MATTER_ID = "MTR-2026-00901"
MATTER_CODE = "CORP/BLR/0901/2026"
CLIENT_ID = "CLI-00901"
LEAD = "MEM-00001"  # matter lead (name read from members at run time)
TEAM = [(LEAD, "Lead"), ("MEM-00005", "Associate"), ("MEM-00007", "Associate"), ("MEM-00011", "Knowledge Manager")]

Section = tuple[str, list[str]]  # (heading, paragraphs)


# ── Document texts (fictional) ───────────────────────────────────────────────

def spa_sections(cure_days_words: str, cure_days: int) -> list[tuple[str, list[Section]]]:
    return [
        ("ARTICLE I — DEFINITIONS AND INTERPRETATION", [
            ("1.1 Definitions", [
                "In this Agreement, unless the context otherwise requires: \"Business Day\" means a day on which scheduled banks are open for business in Bengaluru and Mumbai; \"Closing\" means completion of the sale and purchase of the Sale Shares in accordance with Article V; \"Company\" means Acme Technologies Private Limited, a company incorporated under the Companies Act, 2013; \"Long Stop Date\" means 31 March 2027 or such later date as the Parties may agree in writing; \"Material Adverse Effect\" means any event which, individually or together with other events, has had or would reasonably be expected to have a material adverse effect on the business, assets or financial condition of the Company, taken as a whole; \"Purchaser\" means Northbridge Growth Fund II; \"Sale Shares\" means 1,240,000 Series A compulsorily convertible preference shares of the Company; \"Seller\" means Horizon Seed Partners LLP.",
            ]),
            ("1.2 Interpretation", [
                "Headings are for convenience only. References to Articles and Schedules are to the articles of and schedules to this Agreement. The Disclosure Schedule forms part of this Agreement.",
            ]),
        ]),
        ("ARTICLE II — SALE AND PURCHASE", [
            ("2.1 Sale Shares", [
                "Subject to the terms of this Agreement, the Seller shall sell and the Purchaser shall purchase the Sale Shares, free from all Encumbrances and together with all rights attaching to them at Closing.",
            ]),
            ("2.2 Consideration", [
                "The aggregate consideration for the Sale Shares is INR 186,00,00,000 (Indian Rupees One Hundred and Eighty-Six Crore), payable at Closing by wire transfer to the Seller's designated account, subject to applicable withholding tax.",
            ]),
        ]),
        ("ARTICLE III — CONDITIONS PRECEDENT", [
            ("3.1 Conditions", [
                "Closing is conditional on: (a) the Company's board and shareholders approving the transfer and the amended articles of association; (b) the Purchaser receiving the waiver of pre-emption rights from existing shareholders; (c) no Material Adverse Effect having occurred; and (d) any filing required under the Foreign Exchange Management (Non-debt Instruments) Rules, 2019 having been made.",
            ]),
            ("3.2 Satisfaction", [
                "Each Party shall use reasonable endeavours to satisfy the conditions for which it is responsible as soon as practicable and in any event before the Long Stop Date.",
            ]),
        ]),
        ("ARTICLE IV — WARRANTIES", [
            ("4.1 Seller Warranties", [
                "The Seller warrants to the Purchaser that each statement in Schedule 2 is true and accurate on the date of this Agreement and at Closing, save as fairly disclosed in the Disclosure Schedule.",
            ]),
            ("4.2 Company Warranties", [
                "The Company, as confirming party, gives the business warranties in Schedule 3, including warranties as to financial statements, intellectual property, employees and compliance with law.",
            ]),
        ]),
        ("ARTICLE V — CLOSING", [
            ("5.1 Closing Date", [
                "Closing shall take place on the fifth Business Day after the last condition in Article III is satisfied or waived, or on such other date as the Parties agree.",
            ]),
        ]),
        ("ARTICLE IX — INDEMNIFICATION", [
            ("9.1 Indemnity", [
                "The Seller shall indemnify the Purchaser against all Losses arising from any breach of the Seller Warranties or of any covenant of the Seller under this Agreement.",
            ]),
            ("9.2 Limitations", [
                "The aggregate liability of the Seller for claims under the Seller Warranties (other than Fundamental Warranties and claims arising from fraud) shall not exceed 20% of the consideration. No claim may be brought unless notified within 24 months after Closing.",
            ]),
        ]),
        ("ARTICLE XII — TERMINATION", [
            ("12.1 Termination by Mutual Consent", [
                "This Agreement may be terminated at any time before Closing by mutual written consent of the Seller and the Purchaser.",
            ]),
            ("12.2 Termination for Failure to Close", [
                "Either the Seller or the Purchaser may terminate this Agreement by written notice if Closing has not occurred on or before the Long Stop Date, provided that the right to terminate under this Clause 12.2 shall not be available to a Party whose breach of this Agreement has been the principal cause of the failure to close.",
            ]),
            ("12.3 Termination for Material Breach", [
                f"A Party may terminate this Agreement by written notice to the other Party if the other Party commits a material breach of this Agreement which, if capable of remedy, remains uncured for a period of {cure_days_words} ({cure_days}) days after receipt of written notice specifying the breach and requiring it to be remedied.",
            ]),
            ("12.4 Regulatory Termination", [
                "The Purchaser may terminate this Agreement by written notice if any Governmental Authority issues an order, decree or ruling that permanently restrains or prohibits the transactions contemplated by this Agreement and such order has become final and non-appealable.",
            ]),
            ("12.5 Effect of Termination", [
                "On termination under this Article XII, this Agreement shall cease to have effect except for Clauses 12.5 and 12.6 and Articles XIII and XIV, and termination shall not affect any rights or liabilities of a Party accrued before termination.",
            ]),
            ("12.6 Break Fee", [
                "If this Agreement is terminated by the Purchaser under Clause 12.3 following a material breach by the Seller, the Seller shall pay the Purchaser a break fee of INR 2,50,00,000 within ten Business Days, which the Parties agree is a genuine pre-estimate of the Purchaser's costs and not a penalty.",
            ]),
        ]),
        ("ARTICLE XIII — CONFIDENTIALITY", [
            ("13.1 Confidential Information", [
                "Each Party shall keep confidential the terms of this Agreement and all information received from the other Party, save as required by law or a stock exchange, or with the other Party's prior written consent.",
            ]),
        ]),
        ("ARTICLE XIV — GOVERNING LAW AND DISPUTE RESOLUTION", [
            ("14.1 Governing Law", [
                "This Agreement is governed by the laws of India.",
            ]),
            ("14.2 Arbitration", [
                "Any dispute arising out of or in connection with this Agreement shall be referred to arbitration by a tribunal of three arbitrators under the Arbitration and Conciliation Act, 1996. The seat of arbitration shall be Mumbai and the language English.",
            ]),
        ]),
    ]


BOARD_RESOLUTION = [
    ("CERTIFIED TRUE COPY OF THE RESOLUTIONS OF THE BOARD OF DIRECTORS OF ACME TECHNOLOGIES PRIVATE LIMITED", [
        ("Meeting", [
            "Passed at the meeting of the Board of Directors held on 12 September 2026 at the registered office of the Company in Bengaluru, at which a quorum was present throughout.",
        ]),
        ("1. Approval of transfer of Series A preference shares", [
            "RESOLVED THAT, pursuant to the articles of association of the Company and subject to the approval of the shareholders, consent of the Board be and is hereby accorded to the transfer of 1,240,000 Series A compulsorily convertible preference shares from Horizon Seed Partners LLP to Northbridge Growth Fund II.",
        ]),
        ("2. Amendment of articles of association", [
            "RESOLVED FURTHER THAT the draft amended articles of association, incorporating the investor rights agreed in the Shareholders Agreement dated on or about the date of Closing, be placed before the shareholders for approval by special resolution under Section 14 of the Companies Act, 2013.",
        ]),
        ("3. Authorisation", [
            "RESOLVED FURTHER THAT Ms Riya Anand, Director, and Mr Kabir Sethi, Company Secretary, be and are hereby severally authorised to sign all documents and file all forms with the Registrar of Companies and the Reserve Bank of India as may be required to give effect to these resolutions.",
        ]),
    ]),
]

EMPLOYMENT_AGREEMENT = [
    ("EMPLOYMENT AGREEMENT — CHIEF TECHNOLOGY OFFICER", [
        ("1. Parties", [
            "This Agreement is made between Acme Technologies Private Limited (the \"Company\") and Mr Arvind Rao (the \"Executive\").",
        ]),
        ("2. Appointment and Term", [
            "The Company appoints the Executive as Chief Technology Officer with effect from 1 October 2026. The appointment continues until terminated in accordance with Clause 8.",
        ]),
        ("5. Remuneration", [
            "The Executive shall receive fixed annual compensation of INR 1,20,00,000 and shall be eligible for grants under the Company's Employee Stock Option Plan, subject to the plan rules and vesting over four years with a one-year cliff.",
        ]),
        ("7. Non-Solicitation", [
            "For twelve months after termination, the Executive shall not solicit any employee or customer of the Company. The Parties acknowledge that post-employment restraints of trade are subject to Section 27 of the Indian Contract Act, 1872.",
        ]),
        ("8. Termination", [
            "Either party may terminate this Agreement by giving three months' written notice. The Company may terminate immediately for cause, including gross misconduct or material breach of this Agreement that is not remedied within fifteen days of notice.",
        ]),
        ("9. Change of Control", [
            "If the Executive's employment is terminated without cause within twelve months after a Change of Control, all unvested options shall vest in full (double-trigger acceleration).",
        ]),
    ]),
]

DISCLOSURE_SCHEDULE = [
    ("DISCLOSURE SCHEDULE", [
        ("General disclosures", [
            "The Seller and the Company disclose the contents of the virtual data room as at 10 September 2026, including all documents listed in the data room index.",
        ]),
        ("Specific disclosure against Warranty 3.7 (Litigation)", [
            "The Company is a respondent in a consumer complaint before the District Consumer Disputes Redressal Commission, Bengaluru, claiming INR 38,00,000 for alleged service outages. The Company has denied liability.",
        ]),
        ("Specific disclosure against Warranty 3.12 (Intellectual Property)", [
            "The source code for the Company's analytics module was partly developed by an independent contractor whose assignment of intellectual property was executed on 3 August 2026, after the work was delivered.",
        ]),
        ("Specific disclosure against Warranty 3.15 (Employees)", [
            "Two senior engineers have given notice of resignation effective 30 November 2026.",
        ]),
    ]),
]

DOCUMENTS = [
    # (relative path in the matter, document type, doc_date offset from anchor, sections)
    ("Transaction Documents/Share Purchase Agreement.docx", "Share Purchase Agreement", -20, spa_sections("thirty", 30)),
    ("Corporate Approvals/Board Resolution.docx", "Board Resolution", -12, BOARD_RESOLUTION),
    ("Employment/Employment Agreement - CTO.docx", "Employment Agreement", -9, EMPLOYMENT_AGREEMENT),
    ("Diligence/Disclosure Schedule.docx", "Disclosure Schedule", -14, DISCLOSURE_SCHEDULE),
]


def build_docx(title: str, sections: list[tuple[str, list[Section]]]) -> bytes:
    doc = Document()
    # Fixed metadata so the same content always produces the same bytes (and hash).
    props = doc.core_properties
    props.author = "Precentis demo data"
    props.created = props.modified = datetime(2026, 9, 1, tzinfo=UTC)
    props.last_modified_by = "Precentis demo data"
    props.revision = 1
    doc.styles["Normal"].font.name = "Times New Roman"
    doc.styles["Normal"].font.size = Pt(11.5)
    doc.add_heading(title, level=0)
    for article, clauses in sections:
        doc.add_heading(article, level=1)
        for heading, paragraphs in clauses:
            doc.add_heading(heading, level=2)
            for text in paragraphs:
                doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── Seeding ───────────────────────────────────────────────────────────────────

def ensure_matter(anchor: date) -> None:
    with connect() as conn, conn.transaction():
        conn.execute(
            """
            INSERT INTO clients (client_id, name, industry, size, headquarters, locations)
            VALUES (%s, 'Acme Technologies Private Limited', 'Technology', 'Growth-stage', 'Bengaluru', ARRAY['Bengaluru', 'Pune'])
            ON CONFLICT (client_id) DO NOTHING
            """,
            (CLIENT_ID,),
        )
        conn.execute(
            """
            INSERT INTO matters (matter_id, matter_code, title, client_id, client_name, opposing_party,
                                 practice_area, matter_type, jurisdiction, court, opened_date, status,
                                 office, legal_issues, facts)
            VALUES (%(id)s, %(code)s, 'Acme Technologies — Series B Financing', %(cid)s,
                    'Acme Technologies Private Limited', 'Horizon Seed Partners LLP (Seller)',
                    'Corporate', 'Transaction', 'India', NULL, %(opened)s, 'Open', 'Delhi',
                    ARRAY['Share transfer', 'Termination rights', 'Warranties and indemnities', 'FEMA filings'],
                    ARRAY['Northbridge Growth Fund II is acquiring 1,240,000 Series A CCPS from Horizon Seed Partners LLP.',
                          'Acme Technologies is the confirming party; the Board approved the transfer on 12 September 2026.',
                          'Long Stop Date is 31 March 2027.'])
            ON CONFLICT (matter_id) DO NOTHING
            """,
            {"id": MATTER_ID, "code": MATTER_CODE, "cid": CLIENT_ID, "opened": anchor - timedelta(days=30)},
        )
        conn.execute(
            """
            INSERT INTO permissions (matter_id, classification, restricted, practice_area, allowed_members)
            VALUES (%s, 'confidential', FALSE, 'Corporate', %s)
            ON CONFLICT (matter_id) DO NOTHING
            """,
            (MATTER_ID, [m for m, _ in TEAM]),
        )
        for member, role in TEAM:
            conn.execute(
                """
                INSERT INTO matter_members (matter_id, member_id, role_on_matter)
                VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (MATTER_ID, member, role),
            )
        for i, (days, kind, title) in enumerate([
            (7, "compliance", "Shareholders' EGM to approve amended articles"),
            (21, "filing", "FC-TRS filing with authorised dealer bank"),
            (188, "limitation", "Long Stop Date under SPA Clause 12.2"),
        ]):
            conn.execute(
                """
                INSERT INTO court_deadlines (deadline_id, matter_id, title, kind, due_date, court, owner_member_id, status)
                VALUES (%s, %s, %s, %s, %s, 'Transaction', %s, 'open')
                ON CONFLICT (deadline_id) DO UPDATE SET due_date = EXCLUDED.due_date, title = EXCLUDED.title
                """,
                (f"DL-ACME-{i + 1}", MATTER_ID, title, kind, anchor + timedelta(days=days), LEAD),
            )


def upload_documents() -> dict:
    from app.ingest.upload_batch import create_upload_batch, process_upload_batch

    with connect() as conn:
        present = {
            r["title"]
            for r in conn.execute("SELECT title FROM documents WHERE matter_id = %s", (MATTER_ID,)).fetchall()
        }
    files = [
        (rel, build_docx(Path(rel).stem, sections))
        for rel, _, _, sections in DOCUMENTS
        if Path(rel).name not in present
    ]
    if not files:
        return {"status": "up to date", "indexed": 0, "skipped": len(DOCUMENTS), "failed": 0, "errors": []}
    batch = create_upload_batch(matter_id=MATTER_ID, files=files, created_by=LEAD)
    return process_upload_batch(batch["batch_id"], created_by=LEAD)


def set_metadata(anchor: date) -> dict[str, str]:
    """Document type and date — what a lawyer sets on upload. Returns title → id."""
    ids: dict[str, str] = {}
    with connect() as conn, conn.transaction():
        for rel, dtype, offset, _ in DOCUMENTS:
            title = Path(rel).name
            row = conn.execute(
                "SELECT document_id FROM documents WHERE matter_id = %s AND title = %s ORDER BY ingested_at LIMIT 1",
                (MATTER_ID, title),
            ).fetchone()
            if row:
                ids[title] = row["document_id"]
                conn.execute(
                    "UPDATE documents SET document_type = %s, doc_date = %s WHERE document_id = %s",
                    (dtype, anchor + timedelta(days=offset), row["document_id"]),
                )
    return ids


def add_spa_second_version(spa_id: str) -> str:
    """Seller's mark-up: cure period shortened from 30 to 15 days (for compare demos)."""
    from app.documents import create_version, list_versions
    from app.storage.object_store import build_storage_key, get_object_store

    if len(list_versions(spa_id)) >= 2:
        # Make sure the index holds the current (v2) text — earlier runs may predate
        # the one-version-per-document index fix.
        from app.documents import reindex_current_version
        from app.embeddings.pending import embed_pending_chunks

        out = reindex_current_version(spa_id)
        embed_pending_chunks([spa_id])
        return f"exists ({out['version_id']}, {out['chunk_count']} chunks indexed)"
    from app.config import settings
    from app.ingest.extractors.dispatch import extract_from_bytes

    data = build_docx("Share Purchase Agreement", spa_sections("fifteen", 15))
    extracted = extract_from_bytes("Share Purchase Agreement.docx", data)
    key = build_storage_key(
        tenant_id=settings.tenant_id,
        client_id=CLIENT_ID,
        matter_id=MATTER_ID,
        document_id=spa_id,
        version_number=2,
        filename="Share Purchase Agreement.docx",
    )
    uri = get_object_store().put(
        key, data, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    with connect() as conn:
        lead = conn.execute("SELECT name FROM members WHERE member_id = %s", (LEAD,)).fetchone()
    v = create_version(
        document_id=spa_id,
        body=extracted.text,
        title="Share Purchase Agreement.docx",
        author_name=lead["name"] if lead else LEAD,
        source="upload",
        version_status="draft",
        change_summary="Seller mark-up: cure period in Clause 12.3 reduced from 30 to 15 days",
        storage_uri=uri,
        page_spans=extracted.pages,
        folder_path="Transaction Documents",
    )
    from app.embeddings.pending import embed_pending_chunks

    embed_pending_chunks([spa_id])
    return v["version_id"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--anchor", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    ensure_matter(args.anchor)
    result = upload_documents()
    ids = set_metadata(args.anchor)
    spa = ids.get("Share Purchase Agreement.docx")
    v2 = add_spa_second_version(spa) if spa else "missing SPA"

    print(f"matter            : {MATTER_ID} Acme Technologies — Series B Financing")
    print(f"upload batch      : {result['status']} (indexed {result['indexed']}, skipped {result['skipped']}, failed {result['failed']})")
    for e in result.get("errors", []):
        print(f"  error           : {e}")
    for title, did in ids.items():
        print(f"document          : {did}  {title}")
    print(f"SPA version 2     : {v2}")
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
