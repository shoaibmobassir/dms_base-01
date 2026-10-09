"""
Comprehensive Test Suite for Integrated Mike Features in FirmOS / DMS Knowledge Base.
Clean-room verification covering:
1. Key Vault & AES-256-GCM Encryption
2. Tabular Reviews & Excel Export
3. Legal Workflows & YAML DAG Execution
4. Word DOCX Native Tracked Changes (<w:ins>, <w:del>) & Clause Diff
5. Word Taskpane Auth Handoff & Selection Endpoints
6. Case Law Citation Tokenizer & CourtListener Client
7. Tamper-Evident Manifest Signing & ZIP Packaging
"""

import io
import json
import zipfile
import pytest
from fastapi.testclient import TestClient
import openpyxl

from app.api.main import app
from app.audit.manifest_signer import get_manifest_signer
from app.auth.handoff import get_auth_handoff_service
from app.auth.key_vault import KeyVault
from app.caselaw.citation_parser import get_citation_parser
from app.caselaw.courtlistener_client import get_courtlistener_client
from app.drafting.clause_diff_service import get_clause_diff_service
from app.drafting.docx_redline_generator import DocxRedlineGenerator
from app.workflows.catalog_loader import get_catalog_loader
from app.workflows.engine import get_workflow_engine


@pytest.fixture
def client():
    return TestClient(app)


# -----------------------------------------------------------------------------
# 1. Key Vault (AES-256-GCM)
# -----------------------------------------------------------------------------
def test_key_vault_encryption_roundtrip():
    vault = KeyVault(master_secret="test-secret-key-vault-firmos-32b")
    raw_key = "sk-ant-api03-abcdef1234567890-secure"
    encrypted = vault.encrypt_key(raw_key)
    assert encrypted != raw_key
    decrypted = vault.decrypt_key(encrypted)
    assert decrypted == raw_key


def test_key_vault_tamper_detection():
    vault = KeyVault(master_secret="test-secret-key-vault-firmos-32b")
    raw_key = "sk-openai-test-key-999"
    encrypted = vault.encrypt_key(raw_key)
    tampered = encrypted[:-4] + "AAAA"
    with pytest.raises(ValueError):
        vault.decrypt_key(tampered)


# -----------------------------------------------------------------------------
# 2. Tabular Reviews & Excel Export
# -----------------------------------------------------------------------------
# Tabular reviews moved to app/tabular (plan 22, W4); see tests/test_tabular.py.


# -----------------------------------------------------------------------------
# 3. Legal Playbooks & Workflow Engine
# -----------------------------------------------------------------------------
def test_workflow_catalog_loader():
    loader = get_catalog_loader()
    wfs = loader.list_workflows()
    assert len(wfs) >= 3
    ids = [w.id for w in wfs]
    assert "cease-and-desist-drafter" in ids
    assert "contract-triage-router" in ids
    assert "master-services-agreement-review" in ids


def test_workflow_api_execution(client):
    req_payload = {
        "workflow_id": "cease-and-desist-drafter",
        "inputs": {
            "rights_holder": "Acme Software Corp",
            "infringing_party": "Pirate Tech Ltd",
            "infringing_details": "Unauthorized reproduction of proprietary source code",
            "remedy_deadline_days": 7,
        },
    }
    resp = client.post("/api/workflows/run", json=req_payload)
    assert resp.status_code == 200
    run_data = resp.json()
    assert run_data["status"] == "completed"
    assert "Acme Software Corp" in run_data["final_output"] or "LEGAL DEMAND" in run_data["final_output"]
    assert "retrieve_firm_cd_precedents" in run_data["step_outputs"]


# -----------------------------------------------------------------------------
# 4. DOCX Track Changes & Clause Diff
# -----------------------------------------------------------------------------
def test_docx_tracked_changes_generator():
    gen = DocxRedlineGenerator(author="FirmOS AI")
    orig = "Customer shall pay within 30 days of invoice receipt."
    rev = "Customer shall pay within 45 business days of verified invoice receipt."
    docx_bytes = gen.create_tracked_diff_docx(orig, rev, title="Payment Terms Redline")
    assert len(docx_bytes) > 0
    # Must be a valid zip / docx archive
    zf = zipfile.ZipFile(io.BytesIO(docx_bytes))
    assert "word/document.xml" in zf.namelist()
    doc_xml = zf.read("word/document.xml").decode("utf-8")
    assert "w:ins" in doc_xml
    assert "w:del" in doc_xml


@pytest.mark.asyncio
async def test_clause_diff_service():
    diff_svc = get_clause_diff_service()
    clause = "Supplier liability shall be uncapped for all indirect and consequential losses."
    res = await diff_svc.analyze_and_redline(
        clause_text=clause,
        clause_type="Limitation of Liability",
        client_stance="Supplier",
    )
    assert res.original_clause == clause
    assert res.risk_severity in ("low", "medium", "high", "critical")
    assert len(res.proposed_redline) > 0


# -----------------------------------------------------------------------------
# 5. Word Taskpane Auth Handoff & Selection Router
# -----------------------------------------------------------------------------
def test_auth_handoff_ticket_lifecycle():
    svc = get_auth_handoff_service()
    ticket = svc.create_ticket("MEM-00001", "lawyer@firm.com")
    assert ticket.startswith("TKT-")

    # Exchange once -> succeeds
    session = svc.exchange_ticket(ticket)
    assert session is not None
    assert session["member_id"] == "MEM-00001"

    # Replay -> fails (one-time token)
    assert svc.exchange_ticket(ticket) is None


def test_word_selection_api(client):
    resp = client.post(
        "/api/word/analyze-selection",
        json={"selection_text": "Governing law shall be English Law.", "action": "explain"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "explain"
    assert "analysis" in data


# -----------------------------------------------------------------------------
# 6. Case Law & Citation Verification
# -----------------------------------------------------------------------------
def test_citation_parser():
    parser = get_citation_parser()
    text = (
        "Under Miranda v. Arizona, 384 U.S. 436 (1966) and 123 F.3d 456, "
        "as well as 42 U.S.C. § 1983, constitutional rights are enforceable."
    )
    citations = parser.extract_citations(text)
    assert len(citations) >= 3
    normalized = [c.normalized_citation for c in citations]
    assert any("384 U.S. 436" in n for n in normalized)
    assert any("123 F.3d 456" in n for n in normalized)
    assert any("42 U.S.C. § 1983" in n for n in normalized)


import httpx as _httpx

_REAL_ASYNC_CLIENT = _httpx.AsyncClient


def _mock_courtlistener(monkeypatch, handler):
    from app.caselaw import courtlistener_client as cl

    monkeypatch.setattr(cl.httpx, "AsyncClient",
                        lambda **kw: _REAL_ASYNC_CLIENT(transport=_httpx.MockTransport(handler), **kw))


@pytest.mark.asyncio
async def test_courtlistener_client_resolves_without_claiming_treatment(monkeypatch):
    import httpx
    from app.caselaw.courtlistener_client import CourtListenerClient

    _mock_courtlistener(monkeypatch, lambda req: httpx.Response(200, json={"results": [
        {"caseName": "Miranda v. Arizona", "court": "Supreme Court", "dateFiled": "1966-06-13",
         "status": "Precedential", "snippet": "...", "absolute_url": "/opinion/1/miranda/"}]}))
    opinion = await CourtListenerClient(api_token="t").verify_citation("384 U.S. 436")
    assert opinion.verified
    assert opinion.case_name == "Miranda v. Arizona"
    assert opinion.status == {"signal": "unknown", "source": "none"}


@pytest.mark.asyncio
async def test_courtlistener_outage_is_never_verified(monkeypatch):
    """Design test R13: a provider failure must not produce a verified authority."""
    import httpx
    from app.caselaw.courtlistener_client import CourtListenerClient

    def boom(req):
        raise httpx.ConnectError("offline")

    _mock_courtlistener(monkeypatch, boom)
    client = CourtListenerClient(api_token="t")
    opinion = await client.verify_citation("999 U.S. 999")
    assert not opinion.verified
    assert opinion.resolution == "provider_error"
    assert opinion.case_name is None
    assert opinion.status["signal"] == "unknown"
    assert "999 U.S. 999" not in client._cache  # transient failures are not cached

    _mock_courtlistener(monkeypatch, lambda req: httpx.Response(200, json={"results": []}))
    assert (await client.verify_citation("999 U.S. 999")).resolution == "not_found"



# -----------------------------------------------------------------------------
# 7. Tamper-Evident Export Packaging & Cryptographic Manifest Verification
# -----------------------------------------------------------------------------
def test_manifest_signer_and_verifier():
    signer = get_manifest_signer()
    files = [
        ("report.md", b"# Legal Due Diligence Report\nAll clear."),
        ("data.csv", b"doc_id,risk\nDOC-1,low\nDOC-2,high\n"),
    ]
    meta = {"matter_id": "MAT-00123", "lead_lawyer": "Partner Jane"}

    zip_bytes = signer.build_signed_export_zip("Due Diligence Export", files, meta)
    assert len(zip_bytes) > 0

    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    assert "MANIFEST.json" in zf.namelist()
    assert "report.md" in zf.namelist()
    assert "data.csv" in zf.namelist()

    manifest_json = zf.read("MANIFEST.json").decode("utf-8")
    assert signer.verify_manifest(manifest_json) is True

    # Test tampering
    tampered_manifest = manifest_json.replace("Due Diligence Export", "Forged Document")
    assert signer.verify_manifest(tampered_manifest) is False
