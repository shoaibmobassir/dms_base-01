"""Claim-level grounding: verdict handling, span offsets, figure guard and answer rewriting.

The verifier model is replaced by a scripted judge that picks candidates by text, so these
tests pin the mechanics (candidate pools, offsets, removal, renumbering) without a network.
"""
from __future__ import annotations

import json
import re

from app.grounding.compose import ground_answer, split
from app.grounding.verify import (
    CONTRADICTED,
    PARTIAL,
    SUPPORTED,
    UNSUPPORTED,
    Claim,
    Source,
    missing_facts,
    segment,
    verify_claims,
)

BOARD = (
    "[Page 1]\nBoard Resolution\n\n"
    "Passed at the meeting of the Board of Directors held on 12 September 2026 at the registered office "
    "of the Company in Bengaluru, at which a quorum was present throughout.\n\n"
    "Approval of transfer of Series A preference shares\n"
    "RESOLVED THAT, subject to the approval of the shareholders, consent of the Board be and is hereby "
    "accorded to the transfer of 1,240,000 Series A compulsorily convertible preference shares.\n"
)
SPA = (
    "[Page 2]\nAny dispute shall be referred to arbitration by a tribunal of three arbitrators. "
    "The seat of arbitration shall be Mumbai and the language English.\n"
)


def scripted_judge(rules: dict[str, tuple[str, list[str]]]):
    """rules: substring of unit → (verdict, substrings of candidates to use)."""

    def call(messages):
        body = messages[-1]["content"]
        units = []
        for block in body.split("UNIT ")[1:]:
            num, _, rest = block.partition(": ")
            lines = rest.splitlines()
            unit_text = lines[0]
            cands = {m.group(1): m.group(2) for m in re.finditer(r"^\s+(c\d+) \[[^\]]*\]: (.*)$", rest, re.M)}
            verdict, use = "unsupported", []
            kind = "claim"
            for needle, (v, picks) in rules.items():
                if needle in unit_text:
                    verdict = v
                    use = [cid for cid, text in cands.items() if any(p in text for p in picks)]
                    kind = "non_claim" if v == "non_claim" else "claim"
            units.append({"i": int(num), "kind": kind, "use": use, "verdict": verdict, "missing": ""})
        return json.dumps({"units": units})

    return call


def test_segment_splits_headings_and_skips_page_markers():
    parts = [BOARD[s:e] for s, e in segment(BOARD)]
    assert "Board Resolution" in parts
    assert "Approval of transfer of Series A preference shares" in parts
    assert any(p.startswith("RESOLVED THAT") for p in parts)
    assert not any("[Page" in p for p in parts)


def test_missing_facts_normalises_amounts_and_dates():
    assert not missing_facts("Consideration is INR 186 crore.", "INR 186,00,00,000 (One Hundred and Eighty-Six Crore)")
    assert not missing_facts("Approved on 12.09.2026.", "held on 12 September 2026")
    assert missing_facts("Approved on 12 September 2026.", "consent is accorded to the transfer") == {"12", "september", "2026"}


def test_compound_claim_gets_both_spans_with_exact_offsets():
    src = Source("doc-0", "DOC-06D46C4AD1", "Board Resolution.docx", BOARD)
    claim = Claim("The Board approved the share transfer on 12 September 2026.", cited=["doc-0"],
                  quotes=["Passed at the meeting of the Board of Directors held on 12 September 2026"])
    judge = scripted_judge({"approved": (SUPPORTED, ["Passed at the meeting", "RESOLVED THAT"])})
    [out] = verify_claims([claim], [src], judge)
    assert out.support == SUPPORTED
    assert len(out.spans) == 2
    for sp in out.spans:
        assert " ".join(BOARD[sp.start:sp.end].split()) == sp.quote
        assert sp.page == 1


def test_figure_guard_downgrades_a_waved_through_date():
    src = Source("doc-0", "DOC-06D46C4AD1", "Board Resolution.docx", BOARD)
    claim = Claim("The Board approved the transfer on 14 September 2026.", cited=["doc-0"])
    judge = scripted_judge({"approved": (SUPPORTED, ["RESOLVED THAT"])})
    [out] = verify_claims([claim], [src], judge)
    assert out.support == PARTIAL
    assert "14" in out.reason


def test_judge_failure_fails_closed():
    src = Source("doc-0", "DOC-06D46C4AD1", "Board Resolution.docx", BOARD)

    def broken(_messages):
        raise RuntimeError("provider down")

    [out] = verify_claims([Claim("The Board approved the transfer.", cited=["doc-0"])], [src], broken)
    assert out.support == UNSUPPORTED


def test_sharded_judge_maps_each_verdict_back_to_its_own_claim():
    board = Source("doc-0", "DOC-06D46C4AD1", "Board Resolution.docx", BOARD)
    spa = Source("doc-1", "DOC-0A1", "SPA.docx", SPA)
    claims = [
        Claim("The Board approved the transfer of shares.", cited=["doc-0"]),
        Claim("The seat of arbitration is Mumbai.", cited=["doc-1"]),
        Claim("The tribunal has three arbitrators.", cited=["doc-1"]),
        Claim("The meeting was held in Bengaluru.", cited=["doc-0"]),
        Claim("The shares are held in London.", cited=["doc-0"]),
    ]
    inner = scripted_judge({
        "approved": (SUPPORTED, ["RESOLVED THAT"]), "seat": (SUPPORTED, ["seat of arbitration"]),
        "tribunal": (SUPPORTED, ["three arbitrators"]), "Bengaluru": (SUPPORTED, ["Bengaluru"]),
    })
    calls: list[int] = []

    def judge(messages):
        calls.append(messages[-1]["content"].count("UNIT "))
        return inner(messages)

    verify_claims(claims, [board, spa], judge, batch_size=2)
    assert sorted(calls) == [1, 2, 2]
    assert [c.support for c in claims] == [SUPPORTED] * 4 + [UNSUPPORTED]
    assert claims[1].spans[0].key == "doc-1" and "Mumbai" in claims[1].spans[0].quote
    assert claims[3].spans[0].key == "doc-0" and "Bengaluru" in claims[3].spans[0].quote


def test_one_failed_shard_fails_closed_only_for_its_claims():
    src = Source("doc-0", "DOC-06D46C4AD1", "Board Resolution.docx", BOARD)
    claims = [Claim("The Board approved the transfer.", cited=["doc-0"]),
              Claim("The meeting was held in Bengaluru.", cited=["doc-0"])]
    inner = scripted_judge({"approved": (SUPPORTED, ["RESOLVED THAT"]), "Bengaluru": (SUPPORTED, ["Bengaluru"])})

    def flaky(messages):
        if "Bengaluru" in messages[-1]["content"].split("\n")[0]:
            raise RuntimeError("timeout")
        return inner(messages)

    verify_claims(claims, [src], flaky, batch_size=1)
    assert [c.support for c in claims] == [SUPPORTED, UNSUPPORTED]


def test_ground_answer_rewrites_markers_and_removes_unsupported():
    sources = [
        Source("doc-0", "DOC-06D46C4AD1", "Board Resolution.docx", BOARD),
        Source("doc-1", "DOC-SPA", "Share Purchase Agreement.docx", SPA),
    ]
    text = (
        "I'll check the records.\n\n"
        "- Board approval: the Board approved the transfer on 12 September 2026 [1].\n"
        "- Arbitration is seated in Delhi [2].\n"
        "- Transmission charges comprise PoC charges and reactive charges.\n"
        "The tribunal has three arbitrators [2]."
    )
    cited = {"1": "doc-0", "2": "doc-1"}
    judge = scripted_judge({
        "check the records": ("non_claim", []),
        "Board approval": (SUPPORTED, ["Passed at the meeting", "RESOLVED THAT"]),
        "Delhi": (CONTRADICTED, ["seat of arbitration"]),
        "Transmission": (UNSUPPORTED, []),
        "three arbitrators": (SUPPORTED, ["three arbitrators"]),
    })
    g = ground_answer(
        text, ref_style="markers",
        cited_keys=lambda u: [cited[r] for r in u.refs if r in cited],
        offered_quotes=lambda u: [],
        sources=sources, llm=judge,
    )
    assert "Delhi" not in g.text and "PoC" not in g.text
    assert "Board approval: the Board approved the transfer on 12 September 2026 [1]." in g.text
    assert "The tribunal has three arbitrators [2]." in g.text
    assert "2 statements removed" in g.text
    assert [c["ref"] for c in g.citations] == [1, 2]
    assert g.citations[0]["document_id"] == "DOC-06D46C4AD1" and len(g.citations[0]["quotes"]) == 2
    report = g.report()
    assert report["contradicted"] == 1 and report["removed"] == 2


def test_ground_answer_ids_style_keeps_record_citations():
    sources = [
        Source("DOC-06D46C4AD1", "DOC-06D46C4AD1", "Board Resolution.docx", BOARD, chunk_id="CHK-1"),
        Source("MTR-2026-00901", None, "Matter record", "[MTR-2026-00901] MATTER RECORD — Acme Series B\nStatus: Open"),
    ]
    text = "The matter is open (MTR-2026-00901). The Board accorded consent to the transfer (DOC-06D46C4AD1)."
    judge = scripted_judge({
        "open": (SUPPORTED, ["Status: Open"]),
        "consent": (SUPPORTED, ["RESOLVED THAT"]),
    })
    g = ground_answer(
        text, ref_style="ids",
        cited_keys=lambda u: u.refs, offered_quotes=lambda u: [],
        sources=sources, llm=judge,
    )
    assert "The matter is open (MTR-2026-00901)." in g.text
    assert "The Board accorded consent to the transfer [1]." in g.text
    assert g.citations[0]["chunk_id"] == "CHK-1"


def test_split_keeps_trailing_marker_with_its_sentence():
    units = split("The seat is Mumbai. [2] The language is English [3].", "markers")
    assert [u.refs for u in units] == [["2"], ["3"]]


def test_heading_parser_keeps_whole_words_and_real_numbers():
    from app.documents.canonical import parse_canonical_blocks

    body = "\n\n".join([
        "SECTION Meeting",
        "Passed at the meeting of the Board held on 12 September 2026.",
        "SECTION CERTIFIED TRUE COPY OF THE RESOLUTIONS",
        "SECTION 12.3 Termination for Material Breach",
        "A Party may terminate this Agreement for material breach.",
        "ARTICLE IV Conditions",
        "Section 14 of the Companies Act, 2013 requires a special resolution for any amendment of the articles, "
        "and this paragraph is long enough that it must never be read as a heading even though it starts with Section.",
    ])
    blocks = parse_canonical_blocks(body, "DOC-TEST", "VER-TEST")
    headings = [(b.section_id, b.section_title) for b in blocks if b.block_type == "heading"]
    assert ("meeting", "Meeting") in headings
    assert ("certified-true-copy-of-the-resolutions", "CERTIFIED TRUE COPY OF THE RESOLUTIONS") in headings
    assert ("12.3", "Termination for Material Breach") in headings
    assert ("IV", "Conditions") in headings
    assert blocks[-1].block_type != "heading"


def test_chat_answer_is_rewritten_from_verified_spans(monkeypatch):
    """The Board Resolution case: a compound claim cited to the meeting sentence only."""
    from app.chat import agent
    from app.chat.tools.document_tools import DocEntry

    doc_index = {"doc-0": DocEntry("doc-0", "DOC-06D46C4AD1", "Board Resolution.docx")}
    doc_store = {"doc-0": BOARD}
    full_text = (
        "The Board approved the share transfer on 12 September 2026 [1].\n"
        "Components of transmission charges under CERC are PoC charges.\n"
        "<CITATIONS>[{\"ref\": 1, \"doc_id\": \"doc-0\", \"quotes\": [{\"page\": 1, \"quote\": "
        "\"Passed at the meeting of the Board of Directors held on 12 September 2026\"}]}]</CITATIONS>"
    )
    judge = scripted_judge({
        "approved": (SUPPORTED, ["Passed at the meeting", "RESOLVED THAT"]),
        "transmission": (UNSUPPORTED, []),
    })
    monkeypatch.setattr(agent, "verifier_llms", lambda: [judge])
    text, citations, report = agent.ground_chat_text(full_text, doc_index, doc_store, records=[])
    assert text.startswith("The Board approved the share transfer on 12 September 2026 [1].")
    assert "PoC" not in text and "1 statement removed" in text
    assert citations[0]["document_id"] == "DOC-06D46C4AD1"
    assert [q["quote"][:20] for q in citations[0]["quotes"]] == ["Passed at the meetin", "RESOLVED THAT, subje"]
    assert report["removed"] == 1


def test_firm_record_facts_stay_without_a_document_citation(monkeypatch):
    from app.chat import agent

    records = [agent._record_text({"matters": [{"title": "Acme Series B", "status": "Open"}], "passages": [{"text": "x"}]})]
    judge = scripted_judge({"status": (SUPPORTED, ["status: Open"])})
    monkeypatch.setattr(agent, "verifier_llms", lambda: [judge])
    text, citations, _ = agent.ground_chat_text("The matter's status is Open.", {}, {}, records)
    assert text == "The matter's status is Open." and citations == []


def test_lead_in_is_dropped_when_all_its_items_are_removed():
    sources = [Source("doc-0", "DOC-06D46C4AD1", "Board Resolution.docx", BOARD)]
    text = "Transmission charges comprise:\n- PoC charges\n- Reactive charges\n\nThe Board accorded consent to the transfer [1]."
    judge = scripted_judge({"consent": (SUPPORTED, ["RESOLVED THAT"])})
    g = ground_answer(text, ref_style="markers", cited_keys=lambda u: ["doc-0"] if u.refs else [],
                      offered_quotes=lambda u: [], sources=sources, llm=judge)
    assert "comprise" not in g.text
    assert g.text.startswith("The Board accorded consent to the transfer [1].")


def _element_judge(units: list[dict]):
    return lambda _messages: json.dumps({"units": units})


def test_element_without_a_source_downgrades_supported_to_partial():
    src = Source("doc-0", "DOC-06D46C4AD1", "Board Resolution.docx", BOARD)
    claim = Claim("The Board approved the transfer on 12 September 2026.", cited=["doc-0"],
                  quotes=["Passed at the meeting of the Board of Directors held on 12 September 2026"])
    judge = _element_judge([{"i": 1, "kind": "claim", "verdict": "supported", "elements": [
        {"element": "on 12 September 2026", "use": ["c1"]},
        {"element": "Board approved the transfer", "use": []},
    ]}])
    [out] = verify_claims([claim], [src], judge)
    assert out.support == PARTIAL and "Board approved the transfer" in out.reason


def test_absence_statement_keeps_text_but_loses_its_citation():
    sources = [Source("doc-1", "DOC-E9058749C1", "Share Purchase Agreement.docx", SPA)]
    judge = _element_judge([{"i": 1, "kind": "absence"}])
    g = ground_answer("The SPA does not contain a non-compete covenant [1].", ref_style="markers",
                      cited_keys=lambda u: ["doc-1"], offered_quotes=lambda u: [], sources=sources, llm=judge)
    assert g.text == "The SPA does not contain a non-compete covenant." and g.citations == []


def test_absence_claim_is_removed_when_the_full_document_says_otherwise():
    """acme-13: "no disclosure about employees" while the schedule discloses two resignations."""
    schedule = (
        "[Page 1]\nSpecific disclosure against Warranty 3.7 (Litigation)\n"
        "The Company is a respondent in a consumer complaint claiming INR 38,00,000.\n\n"
        "Specific disclosure against Warranty 3.15 (Employees)\n"
        "Two senior engineers have given notice of resignation effective 30 November 2026.\n"
    )
    passage = Source("DOC-BA2F648943", "DOC-BA2F648943", "Disclosure Schedule.docx", schedule[:120])
    full = Source("DOC-BA2F648943", "DOC-BA2F648943", "Disclosure Schedule.docx", schedule)
    calls = []

    def judge(messages):
        calls.append(messages[0]["content"][:30])
        if "STATEMENT" in messages[-1]["content"]:
            cid = re.search(r"(c\d+) \[[^\]]*\]: Two senior engineers", messages[-1]["content"]).group(1)
            return json.dumps({"units": [{"i": 1, "found": [cid], "what": "employee resignations"}]})
        return json.dumps({"units": [{"i": 1, "kind": "absence"}]})

    g = ground_answer("The Disclosure Schedule contains no disclosure about employees.", ref_style="ids",
                      cited_keys=lambda u: [], offered_quotes=lambda u: [], sources=[passage], llm=judge,
                      full_sources=[full])
    assert "no disclosure about employees" not in g.text
    assert g.removed and g.removed[0]["verdict"] == CONTRADICTED
    assert len(calls) == 2


def test_consensus_needs_every_verifier_to_agree():
    from app.grounding.verify import verify_consensus

    src = Source("doc-0", "DOC-06D46C4AD1", "Board Resolution.docx", BOARD)
    agree = scripted_judge({"approved": (SUPPORTED, ["RESOLVED THAT", "Passed at the meeting"])})
    doubt = scripted_judge({"approved": (UNSUPPORTED, [])})
    both = verify_consensus([Claim("The Board approved the transfer on 12 September 2026.", cited=["doc-0"])], [src], [agree, agree])
    split_vote = verify_consensus([Claim("The Board approved the transfer on 12 September 2026.", cited=["doc-0"])], [src], [agree, doubt])
    assert both[0].support == SUPPORTED
    assert split_vote[0].support == PARTIAL and split_vote[0].spans


def test_pointers_under_a_suggestion_lead_in_are_kept():
    sources = [Source("doc-0", "DOC-06D46C4AD1", "Board Resolution.docx", BOARD)]
    text = ("The documents do not contain the components of transmission charges.\n\n"
            "They would typically be found in:\n"
            "- CERC (Sharing of Inter-State Transmission Charges and Losses) Regulations\n"
            "- The Regulations provide four components: NC, RC, TC and ACC")
    judge = _element_judge([{"i": 1, "kind": "absence"}, {"i": 2, "kind": "non_claim"},
                            {"i": 3, "kind": "non_claim"}, {"i": 4, "kind": "non_claim"}])
    g = ground_answer(text, ref_style="markers", cited_keys=lambda u: [], offered_quotes=lambda u: [],
                      sources=sources, llm=judge)
    assert "Sharing of Inter-State Transmission Charges and Losses) Regulations" in g.text
    assert "four components" not in g.text  # says what the law provides: must be verified, and is not


# ── the Assistant reporting its own edits is not a claim about the documents ──

def test_edit_turn_reports_are_kept_and_never_judged():
    from app.chat.agent import edit_report_detector

    edits = [{"original": "Remuneration", "proposed": "2. Remuneration (renumbered)"}]
    is_report = edit_report_detector(edits)
    for kept in ("I'll fix the numbering now.", "I've renumbered the sections.", "Please accept the edit cards to apply this.",
                 "Summary of changes: one heading renumbered.", "The edit is shown below.",
                 'The heading becomes "2. Remuneration (renumbered)".'):
        assert is_report(kept), kept
    for claim in ("Arbitration is seated in Delhi.", "The agreement runs for two years.", "The Board approved the transfer on 12 September 2026."):
        assert not is_report(claim), claim


def test_ground_answer_keeps_non_claim_units_and_still_removes_unsupported_claims():
    from app.chat.agent import edit_report_detector

    sources = [Source("doc-0", "DOC-06D46C4AD1", "Board Resolution.docx", BOARD)]
    text = "I'll fix the numbering now.\n\nPlease accept the edit cards to apply this.\n\nArbitration is seated in Delhi."
    judged: list[str] = []

    def judge(messages):
        judged.append(messages[-1]["content"])
        return json.dumps({"units": [{"i": 1, "kind": "claim", "elements": [], "verdict": "unsupported", "missing": "x"}]})

    g = ground_answer(text, ref_style="markers", cited_keys=lambda u: [], offered_quotes=lambda u: [], sources=sources, llm=judge,
                      non_claim=edit_report_detector([{"proposed": "2. Remuneration"}]))
    assert "I'll fix the numbering now." in g.text and "Please accept the edit cards" in g.text
    assert "Delhi" not in g.text and "1 statement removed" in g.text
    assert all("fix the numbering" not in j and "Please accept" not in j for j in judged)  # never sent to the judge


def test_a_quoted_clause_number_does_not_end_the_sentence():
    text = 'The edit card shows the change from "3. Remuneration" to "2. Remuneration", to correct the sequence.'
    assert len(split(text, "markers")) == 1
    # a real sentence that happens to end in a number still ends there
    assert len(split("The notice period is set by Clause 8. The Company may terminate earlier.", "markers")) == 2


def test_the_sentences_a_live_edit_turn_produced_are_all_reports():
    from app.chat.agent import edit_report_detector

    is_report = edit_report_detector([{"original": "3. Remuneration", "proposed": "2. Remuneration"}])
    for s in ("The clauses jump from 1 to 3, so I need to renumber clause 3 as clause 2.",
              'The edit card shows the change from "3. Remuneration" to "2. Remuneration", to correct the sequence.',
              "Accept the card to apply the change directly to the document."):
        assert is_report(s), s
