#!/usr/bin/env python3
"""Build an eval dataset of questions and expected answers from the 7 real PDFs.

Reasoning:
  We need ground-truth Q&A pairs to:
  1. Detect wrong/hallucinated answers (the user reported wrong info)
  2. Verify matter_id and tags are attached correctly
  3. Measure retrieval quality (is the right document found?)
  4. Test abstention on out-of-scope queries

  Questions are manually crafted based on the PDF filenames and known content
  domains (Indian energy regulation, CERC/APTEL, force majeure, etc.).
"""
from __future__ import annotations

import json
from pathlib import Path

EVALS_DIR = Path(__file__).parent


def build_dataset() -> list[dict]:
    questions: list[dict] = []
    qid = 0

    def add(qtype: str, question: str, **extra) -> None:
        nonlocal qid
        qid += 1
        questions.append({
            "question_id": f"DMS-Q-{qid:03d}",
            "type": qtype,
            "question": question,
            **extra,
        })

    # ═══════════════════════════════════════════════════════════════════════
    # FACTUAL questions — answers must come from specific documents
    # ═══════════════════════════════════════════════════════════════════════

    # Affidavit - CA 10046 of 2025.pdf
    add("factual",
        "What is the case number of the affidavit filed in the Civil Appeal?",
        expected_documents=["Affidavit - CA 10046 of 2025.pdf"],
        expected_answer_contains=["CA 10046 of 2025", "Civil Appeal"],
        expected_tags=["Affidavit", "Civil Appeal"])

    add("factual",
        "What are the key arguments in the affidavit for CA 10046 of 2025?",
        expected_documents=["Affidavit - CA 10046 of 2025.pdf"],
        expected_tags=["Affidavit"])

    # BRIEF NOTE - MSEDCL
    add("factual",
        "What submissions were made on behalf of MSEDCL as Respondent No. 2?",
        expected_documents=["BRIEF NOTE OF SUBMISSIONS ON BEHALF OF RESPONDENT NO. 2, MSEDCL.pdf"],
        expected_answer_contains=["MSEDCL", "Respondent"],
        expected_tags=["MSEDCL", "Regulatory"])

    add("factual",
        "What is MSEDCL's position in the brief note of submissions?",
        expected_documents=["BRIEF NOTE OF SUBMISSIONS ON BEHALF OF RESPONDENT NO. 2, MSEDCL.pdf"],
        expected_answer_contains=["MSEDCL"])

    # Final Reply (310-MP-2026)
    add("factual",
        "What are the key points in the Final Reply for 310-MP-2026?",
        expected_documents=["Final Reply (310-MP-2026).pdf"],
        expected_answer_contains=["310-MP-2026"],
        expected_tags=["Regulatory"])

    add("factual",
        "What petition is the final reply 310-MP-2026 responding to?",
        expected_documents=["Final Reply (310-MP-2026).pdf"],
        expected_answer_contains=["310-MP-2026"])

    # MSEDCL Note in APL. 163 of 2018
    add("factual",
        "What is the MSEDCL note about in Appeal 163 of 2018?",
        expected_documents=["MSEDCL Note in APL. 163 of 2018.pdf"],
        expected_answer_contains=["APL", "163", "2018"],
        expected_tags=["MSEDCL", "Regulatory"])

    add("factual",
        "What is the appeal number in the MSEDCL note filed before APTEL?",
        expected_documents=["MSEDCL Note in APL. 163 of 2018.pdf"],
        expected_answer_contains=["163", "2018"])

    # Rejoinder to Reply to Impleadment Application
    add("factual",
        "What arguments are raised in the rejoinder to the impleadment application reply?",
        expected_documents=["Rejoinder to Reply to Impleadment Application.pdf"],
        expected_tags=["Impleadment"])

    # Rejoinder to reply of IA
    add("factual",
        "What is the rejoinder to the reply of the Interlocutory Application about?",
        expected_documents=["Rejoinder to reply of IA.pdf"],
        expected_tags=["Impleadment"])

    # WRITTEN SUBMISSION - Vector Green - Petition No. 22 of 2026
    add("factual",
        "What are Vector Green's written submissions in Petition No. 22 of 2026?",
        expected_documents=["WRITTEN SUBMISSION IN PETITION NO. 22 OF 2026 (VECTOR GREEN) 01.08.2026.pdf"],
        expected_answer_contains=["Vector Green", "Petition No. 22"],
        expected_tags=["Regulatory", "Tariff"])

    add("factual",
        "What is the petition number for the Vector Green case?",
        expected_documents=["WRITTEN SUBMISSION IN PETITION NO. 22 OF 2026 (VECTOR GREEN) 01.08.2026.pdf"],
        expected_answer_contains=["22 of 2026"],
        expected_tags=["Regulatory"])

    add("factual",
        "When was the written submission for Vector Green filed?",
        expected_documents=["WRITTEN SUBMISSION IN PETITION NO. 22 OF 2026 (VECTOR GREEN) 01.08.2026.pdf"],
        expected_answer_contains=["01.08.2026", "August"])

    # ═══════════════════════════════════════════════════════════════════════
    # METADATA questions — test that matter_id, tags, document_type are returned
    # ═══════════════════════════════════════════════════════════════════════

    add("metadata",
        "Which documents relate to MSEDCL?",
        expected_documents=[
            "BRIEF NOTE OF SUBMISSIONS ON BEHALF OF RESPONDENT NO. 2, MSEDCL.pdf",
            "MSEDCL Note in APL. 163 of 2018.pdf",
        ],
        expected_tags=["MSEDCL"])

    add("metadata",
        "Which documents are rejoinders?",
        expected_documents=[
            "Rejoinder to Reply to Impleadment Application.pdf",
            "Rejoinder to reply of IA.pdf",
        ],
        expected_document_type="Rejoinder")

    add("metadata",
        "Which documents are filed before CERC?",
        expected_documents=[
            "Final Reply (310-MP-2026).pdf",
            "WRITTEN SUBMISSION IN PETITION NO. 22 OF 2026 (VECTOR GREEN) 01.08.2026.pdf",
        ],
        expected_forum="CERC")

    add("metadata",
        "Which documents relate to Vector Green Energy?",
        expected_documents=[
            "WRITTEN SUBMISSION IN PETITION NO. 22 OF 2026 (VECTOR GREEN) 01.08.2026.pdf",
        ],
        expected_tags=["Regulatory"])

    # ═══════════════════════════════════════════════════════════════════════
    # CROSS-DOCUMENT questions — require synthesizing across multiple PDFs
    # ═══════════════════════════════════════════════════════════════════════

    add("cross_document",
        "What are the different legal proceedings involving MSEDCL across our documents?",
        expected_documents=[
            "BRIEF NOTE OF SUBMISSIONS ON BEHALF OF RESPONDENT NO. 2, MSEDCL.pdf",
            "MSEDCL Note in APL. 163 of 2018.pdf",
        ])

    add("cross_document",
        "Compare the two rejoinder filings — what are they each responding to?",
        expected_documents=[
            "Rejoinder to Reply to Impleadment Application.pdf",
            "Rejoinder to reply of IA.pdf",
        ])

    add("cross_document",
        "What regulatory proceedings are documented across our files?",
        expected_documents=[
            "Final Reply (310-MP-2026).pdf",
            "WRITTEN SUBMISSION IN PETITION NO. 22 OF 2026 (VECTOR GREEN) 01.08.2026.pdf",
            "MSEDCL Note in APL. 163 of 2018.pdf",
        ])

    # ═══════════════════════════════════════════════════════════════════════
    # LEGAL REASONING questions — require understanding legal concepts
    # ═══════════════════════════════════════════════════════════════════════

    add("legal_reasoning",
        "What force majeure arguments have been raised in any of our documents?",
        expected_tags=["Force Majeure"])

    add("legal_reasoning",
        "What tariff-related arguments are present in the Vector Green submission?",
        expected_documents=["WRITTEN SUBMISSION IN PETITION NO. 22 OF 2026 (VECTOR GREEN) 01.08.2026.pdf"],
        expected_tags=["Tariff", "Regulatory"])

    add("legal_reasoning",
        "What is the regulatory framework discussed in the CERC filings?",
        expected_documents=[
            "Final Reply (310-MP-2026).pdf",
            "WRITTEN SUBMISSION IN PETITION NO. 22 OF 2026 (VECTOR GREEN) 01.08.2026.pdf",
        ])

    add("legal_reasoning",
        "What arguments about electricity pricing or PPA compliance are in our documents?",
        expected_tags=["PPA", "Tariff", "Electricity"])

    # ═══════════════════════════════════════════════════════════════════════
    # NEGATIVE questions — should abstain (not in our docs)
    # ═══════════════════════════════════════════════════════════════════════

    add("negative",
        "Have we filed any patent applications for AI technology?",
        expected_documents=[],
        should_abstain=True)

    add("negative",
        "What is our position on cryptocurrency regulation in India?",
        expected_documents=[],
        should_abstain=True)

    add("negative",
        "Do we have any documents about immigration law proceedings?",
        expected_documents=[],
        should_abstain=True)

    add("negative",
        "What merger and acquisition transactions have we advised on?",
        expected_documents=[],
        should_abstain=True)

    add("negative",
        "Have we advised on international arbitration under UNCITRAL rules?",
        expected_documents=[],
        should_abstain=True)

    add("negative",
        "What real estate due diligence reports do we have?",
        expected_documents=[],
        should_abstain=True)

    add("negative",
        "Do we have any employment law advice memos?",
        expected_documents=[],
        should_abstain=True)

    add("negative",
        "What antitrust or competition law matters have we handled?",
        expected_documents=[],
        should_abstain=True)

    # ═══════════════════════════════════════════════════════════════════════
    # EDGE CASES
    # ═══════════════════════════════════════════════════════════════════════

    add("edge",
        "",
        expected_documents=[],
        should_abstain=True,
        description="Empty query should abstain gracefully")

    add("edge",
        "   ",
        expected_documents=[],
        should_abstain=True,
        description="Whitespace-only query should abstain")

    add("edge",
        "asdflkjhasdf random gibberish xyz123",
        expected_documents=[],
        should_abstain=True,
        description="Gibberish query should abstain")

    add("edge",
        "MSEDCL" * 50,
        expected_documents=[
            "BRIEF NOTE OF SUBMISSIONS ON BEHALF OF RESPONDENT NO. 2, MSEDCL.pdf",
            "MSEDCL Note in APL. 163 of 2018.pdf",
        ],
        description="Very long repeated keyword should still retrieve relevant docs")

    add("edge",
        "310-MP-2026",
        expected_documents=["Final Reply (310-MP-2026).pdf"],
        description="Case number only — should find the right document")

    add("edge",
        "petition 22 2026 vector green",
        expected_documents=["WRITTEN SUBMISSION IN PETITION NO. 22 OF 2026 (VECTOR GREEN) 01.08.2026.pdf"],
        description="Keywords without proper formatting — should still match")

    return questions


def main() -> None:
    questions = build_dataset()
    out = EVALS_DIR / "dataset.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    # Print summary
    from collections import Counter
    types = Counter(q["type"] for q in questions)
    print(f"Generated {len(questions)} questions:")
    for qtype, count in sorted(types.items()):
        print(f"  {qtype}: {count}")
    print(f"\nSaved to: {out}")


if __name__ == "__main__":
    main()
