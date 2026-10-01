"""Long documents in the Assistant: outline, addressable reads, match counts, context budget."""
from __future__ import annotations

import json

from app.chat import doc_nav
from app.chat.context import fit_context
from app.chat.tools.document_tools import DocEntry, fetch_documents, find_in_document, get_outline, read_document


def _long_doc(sections: int = 30, paras: int = 12) -> str:
    """Paged text like document_tools.paged_text: ~3 pages per section, numbered headings."""
    parts, page = [], 1
    for s in range(1, sections + 1):
        body = [f"SECTION {s} — Topic {s}"]
        body += [f"{s}.{p} The Supplier shall comply with obligation {s}.{p} in full. " * 6 for p in range(1, paras + 1)]
        for chunk in (body[:5], body[5:9], body[9:]):
            parts.append(f"[Page {page}]\n" + "\n\n".join(chunk))
            page += 1
    return "\n\n".join(parts)


def _index(text: str):
    return {"doc-0": DocEntry("doc-0", "DOC-LONG", "Master Services Agreement.docx", text=text)}


def test_outline_has_one_stable_section_per_heading():
    text = _long_doc()
    rows = doc_nav.outline_rows(text)
    assert [r["section_id"] for r in rows[:3]] == ["s1", "s2", "s3"]
    assert rows[1]["title"] == "Section 2 — Topic 2" and rows[1]["pages"] == "4–6"
    assert doc_nav.outline(text) == doc_nav.outline(text)  # same ids every call


def test_document_without_headings_is_split_into_page_groups():
    text = "\n\n".join(f"[Page {i}]\nplain text on page {i}." for i in range(1, 13))
    titles = [r["title"] for r in doc_nav.outline_rows(text)]
    assert titles == ["Pages 1–5", "Pages 6–10", "Pages 11–12"]


def test_short_document_is_read_whole():
    text = "[Page 1]\nA short letter."
    out = read_document("doc-0", _index(text), {}, max_chars=1000)
    assert out["complete"] and out["text"] == text


def test_long_document_first_read_is_outline_plus_opening_slice():
    text = _long_doc()
    store: dict = {}
    out = read_document("doc-0", _index(text), store, max_chars=8000)
    assert not out["complete"] and len(out["text"]) <= 8000
    assert out["outline"][0]["section_id"] == "s1" and out["next_cursor"] > 0
    assert store["doc-0"] == text, "citations must still be checked against the whole text"


def test_section_and_page_reads_return_exactly_that_part():
    text = _long_doc()
    sec = read_document("doc-0", _index(text), {}, section_id="s7", max_chars=100000)
    assert sec["text"].startswith("[Page 19]\nSECTION 7") and "SECTION 8" not in sec["text"] and "[Page 22]" not in sec["text"]
    pages = read_document("doc-0", _index(text), {}, pages="10-11", max_chars=100000)
    assert "[Page 10]" in pages["text"] and "[Page 11]" in pages["text"] and "[Page 12]" not in pages["text"]
    assert "error" in read_document("doc-0", _index(text), {}, section_id="s999")


def test_cursor_walks_a_long_part_without_gaps_or_overlap():
    text = _long_doc(sections=3, paras=40)
    got, cursor = "", None
    for _ in range(50):
        out = read_document("doc-0", _index(text), {}, section_id="s2", cursor=cursor, max_chars=3000)
        got += text[out["showing"]["chars"][0]:out["showing"]["chars"][1]]
        cursor = out.get("next_cursor")
        if cursor is None:
            break
    sec = doc_nav.section(text, "s2")
    assert got == text[sec.start:sec.end]


def test_find_counts_every_occurrence_and_names_the_section():
    text = _long_doc()
    out = find_in_document("doc-0", "the supplier", _index(text), {}, max_results=5)
    assert out["returned"] == 5 and out["total_matches"] == 30 * 12 * 6
    assert out["matches"][0]["section_id"] == "s1"


def test_fetch_documents_shares_one_budget():
    text = _long_doc()
    index = {f"doc-{i}": DocEntry(f"doc-{i}", f"DOC-{i}", f"d{i}.docx", text=text) for i in range(4)}
    out = fetch_documents(list(index), index, {})
    assert sum(len(d["text"]) for d in out["documents"]) <= 2 * 40000 + 4


def test_get_outline_reports_size_and_sections():
    out = get_outline("doc-0", _index(_long_doc()), {})
    assert out["total_pages"] == 90 and not out["fits_in_one_read"] and len(out["sections"]) == 30


def test_fit_context_stubs_oldest_tool_outputs_but_keeps_the_latest_round():
    big = "x" * 5000
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "a", "function": {"name": "read_document", "arguments": '{"doc_id": "doc-0", "section_id": "s1"}'}}]},
        {"role": "tool", "tool_call_id": "a", "name": "read_document", "content": big},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "b", "function": {"name": "read_document", "arguments": '{"doc_id": "doc-0", "section_id": "s2"}'}}]},
        {"role": "tool", "tool_call_id": "b", "name": "read_document", "content": big},
    ]
    assert fit_context(messages, 6000) == 1
    stub = json.loads(messages[2]["content"])
    assert stub["evicted"] and stub["arguments"] == {"doc_id": "doc-0", "section_id": "s1"}
    assert messages[4]["content"] == big
    assert fit_context(messages, 100000) == 0


def test_working_set_is_carried_into_the_next_turn():
    from types import SimpleNamespace

    from app.chat.agent import build_llm_messages
    from app.chat.context import carried_documents, working_set

    events = [
        {"type": "doc_read", "document_id": "DOC-LONG", "filename": "MSA.docx", "part": "s7 Section 7 — Topic 7"},
        {"type": "doc_find", "document_id": "DOC-LONG", "filename": "MSA.docx", "query": "Supplier"},
        {"type": "doc_read", "document_id": "DOC-LONG", "filename": "MSA.docx", "part": "s7 Section 7 — Topic 7"},
    ]
    ws = working_set(events)
    assert ws == [{"document_id": "DOC-LONG", "filename": "MSA.docx", "parts": ["s7 Section 7 — Topic 7"], "searches": ["Supplier"]}]
    history = [
        SimpleNamespace(role=SimpleNamespace(value="user"), content="edit clause 7", events=None, files=None),
        SimpleNamespace(role=SimpleNamespace(value="assistant"), content="Done.", events=[{"type": "working_set", "documents": ws}], files=None),
    ]
    assert carried_documents(history)[0]["document_id"] == "DOC-LONG"
    index = {"doc-4": DocEntry("doc-4", "DOC-LONG", "MSA.docx")}
    system = build_llm_messages(history, "now also clause 9", index, "n0nce")[0]["content"]
    assert "WORKED ON EARLIER" in system and "doc-4: MSA.docx (read: s7 Section 7 — Topic 7; searched: “Supplier”)" in system
