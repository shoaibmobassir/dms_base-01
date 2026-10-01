"""Grounding accepts facts stated by firm records (person, matter), not only documents.

Record fields are short "Field: value" lines that match the heading heuristic. Treating
them as headings removed every people answer ("who is an expert in sanctions?") as
unsupported. Document headings must still not count as support.
"""
from __future__ import annotations

import json

from app.grounding.verify import Claim, Source, verify_claims

PERSON = Source(
    key="MEM-00004", document_id=None, title="Sami Haddad",
    text="[MEM-00004] PERSON — Sami Haddad, Counsel, Geneva office\nSpecialisations: Sanctions, Chapter VII",
)
HEADING_DOC = Source(key="DOC-00001", document_id="DOC-00001", title="SPA", text="ARTICLE 12 — TERMINATION")


def _judge_using_every_candidate(messages):
    body = messages[-1]["content"]
    cands = [line.split()[0] for line in body.splitlines() if line.startswith("  c")]
    return json.dumps({"units": [{"i": 1, "kind": "claim", "verdict": "supported", "missing": "",
                                  "elements": [{"element": "the fact", "use": cands}]}]})


def test_person_record_fields_support_a_claim():
    claim = Claim(text="Sami Haddad is Counsel and specialises in sanctions.", cited=["MEM-00004"])
    [out] = verify_claims([claim], [PERSON], _judge_using_every_candidate, batch_size=0)
    assert out.support == "supported", out.reason
    assert out.spans and out.spans[0].key == "MEM-00004"


def test_document_heading_alone_still_does_not_support():
    claim = Claim(text="Article 12 allows termination on notice.", cited=["DOC-00001"])
    [out] = verify_claims([claim], [HEADING_DOC], _judge_using_every_candidate, batch_size=0)
    assert out.support != "supported"
