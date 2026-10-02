"""Legal research building blocks that need no database (design doc §22.4–22.8)."""
from __future__ import annotations

import pytest

from app.research.citations import extract_citations, parse_citation
from app.research.formatter import format_citation, judge_name
from app.research.legal_systems import Forum, forum_from_matter, label_for
from app.research.ocr_match import locate_ocr
from app.research.structure import is_chapter_vii, opinion_heading, page_at, page_offsets, segment_decision, segment_resolution


# --- citations (§22.4.1) ----------------------------------------------------

@pytest.mark.parametrize("text,key", [
    ("P.C.I.J., Series A, No. 10", "pcij:A:10"),
    ("PCIJ Ser. A/B No. 53", "pcij:A/B:53"),
    ("Series B, No. 4", "pcij:B:4"),
    ("I.C.J. Reports 1949, p. 4", "icj:1949:4"),
    ("S/RES/1373 (2001)", "unsc:1373"),
    ("resolution 678 (1990)", "unsc:678"),
    ("SC Res. 2375", "unsc:2375"),
    ("UNSCR 1718", "unsc:1718"),
    ("1155 U.N.T.S. 331", "unts:1155:331"),
    ("(2008) 4 SCC 755", "in:scc:2008:4:755"),
    ("AIR 1973 SC 1461", "in:air:1973:sc:1461"),
    ("2023 SCC OnLine SC 123", "in:scconline:2023:sc:123"),
    ("Civil Appeal No. 10046 of 2025", "in:civil-appeal:10046:2025"),
    ("Appeal No. 163 of 2018", "in:appeal:163:2018"),
    ("Petition No. 310/MP/2026", "in:petition:310/MP/2026"),
    ("I.A. No. 1097 of 2026", "in:ia:1097:2026"),
    ("Section 62 of the Electricity Act, 2003", "in:act:electricity-act-2003:s62"),
    ("s. 111(2) of the Electricity Act, 2003", "in:act:electricity-act-2003:s111(2)"),
    ("467 U.S. 837", "us:467 u.s. 837"),
])
def test_citation_forms(text, key):
    cite = parse_citation(f"As held in {text}, the point stands.")
    assert cite is not None and cite.key == key


def test_pinpoints_and_general_assembly_exclusion():
    cites = extract_citations(
        "S/RES/1373 (2001), para. 2; P.C.I.J., Series A, No. 1, p. 25. "
        "General Assembly resolution 2625 (1970) is not a Council resolution."
    )
    assert [c.key for c in cites] == ["unsc:1373", "pcij:A:1"]
    assert cites[0].pinpoint == {"para": 2} and cites[1].pinpoint == {"page": 25}


def test_overlapping_matches_keep_the_longest():
    cites = extract_citations("P.C.I.J., Series A/B, No. 63")
    assert len(cites) == 1 and cites[0].key == "pcij:A/B:63"


# --- structure: passage roles (§22.8, tests R12, R14) -----------------------

NUMBERED = """S/RES/9 (2001)
Decides that all States shall freeze funds; an editorial catalogue summary of the resolution that is
long enough to be more than a masthead, and that a lawyer must never quote as the Council's own words.

The Security Council,
     Recalling its earlier resolutions,
     Acting under Chapter VII of the Charter of the United Nations,
     1.   Decides that all States shall freeze without delay the funds of terrorists;
     2.   Calls upon all States to cooperate;
     3.   Authorizes Member States to inspect cargo;
Annex
     1.   A listed entity
"""

UNNUMBERED = """The Security Council,

Noting with grave concern the armed attack,

Determines that this action constitutes a breach of the peace; and

Calls upon the authorities to withdraw forthwith;
"""


def test_numbered_resolution_roles():
    segs = segment_resolution(NUMBERED)
    roles = [p.role for p in segs]
    assert roles[0] == "headnote"
    ops = [p for p in segs if p.role == "operative"]
    assert [(p.para, p.lead_verb) for p in ops] == [(1, "decides"), (2, "calls"), (3, "authorizes")]
    assert "listed entity" in ops[-1].text  # an annex list restarting at 1 is not a new paragraph
    assert any(p.role == "preamble" and "Recalling" in p.text for p in segs)
    assert is_chapter_vii(NUMBERED)


def test_paragraph_at_top_of_a_scanned_page_is_kept():
    """A form feed (PDF page break) right before "6." must not end the operative part (S/RES/687 lost 29 paragraphs)."""
    text = ("The Security Council,\n     Acting therefore under Chapter VII of the Charter,\n"
            "1. Decides one;\n2. Decides two;\n\x0c3. Decides that Iraq shall unconditionally accept;\n4. Requests four;\n")
    ops = [p for p in segment_resolution(text) if p.role == "operative"]
    assert [p.para for p in ops] == [1, 2, 3, 4]
    assert is_chapter_vii(text)  # "Acting therefore under Chapter VII"
    assert is_chapter_vii("Acting under Articles 39 and 40 of the Charter,")


def test_unnumbered_resolution_counts_operative_clauses():
    segs = segment_resolution(UNNUMBERED)
    ops = [p for p in segs if p.role == "operative"]
    assert [p.para_label for p in ops] == ["unnumbered 1", "unnumbered 2"]
    assert [p.lead_verb for p in ops] == ["determines", "calls"]
    assert [p.role for p in segs][0] == "preamble"
    assert not is_chapter_vii(UNNUMBERED)


def test_opinion_headings_and_pages():
    dissent = "DISSENTING OPINION BY M. ALTAMIRA. [Translation.]\n1 regret that 1 cannot concur.\fPage two"
    assert opinion_heading(dissent) == ("dissent", "M. ALTAMIRA")
    assert opinion_heading("SEPARATE OPINION OF JONKHEER VAN EYSINGA. [Translation.]")[0] == "separate_opinion"
    assert opinion_heading("JUDGMENT OF DECEMBER 12th, 1934") is None
    judgment = "The Court decides.\fMore reasons.\f\nSEPARATE OPINION OF M. SCHUCKING. [Translation.]\nI agree."
    segs = segment_decision(judgment)
    assert [(p.role, p.page) for p in segs] == [("majority", 1), ("separate_opinion", 3)]
    offs = page_offsets(judgment)
    assert len(offs) == 3 and page_at(offs, judgment.index("More")) == 2


# --- binding labels (§22.6, tests R14, R15) ---------------------------------

UNSC = {"legal_system": "international", "kind": "resolution", "provider_kind": "unsc", "chapter_vii": True}
PCIJ = {"legal_system": "international", "kind": "case", "provider_kind": "pcij", "matter_id": "MTR-1", "role": "majority"}


@pytest.mark.parametrize("ch7,verb,role,label", [
    (True, "decides", "operative", "binding"),
    (False, "decides", "operative", "likely_binding"),
    (True, "demands", "operative", "likely_binding"),
    (True, "authorizes", "operative", "not_binding"),
    (True, "calls", "operative", "recommendatory"),
    (True, "welcomes", "operative", "not_binding"),
    (True, "recalling", "preamble", "not_binding"),
    (True, "decides", "headnote", "not_binding"),
])
def test_unsc_labels_are_per_paragraph(ch7, verb, role, label):
    got = label_for({**UNSC, "chapter_vii": ch7}, Forum("international"), {"role": role, "lead_verb": verb})
    assert got.label == label and got.reason


def test_judicial_override_beats_the_verb_rule():
    """S/RES/276 (1970): not Chapter VII, "calls upon", yet held binding in the Namibia Advisory Opinion."""
    res276 = {**UNSC, "chapter_vii": False, "citation": {"number": 276}}
    got = label_for(res276, Forum("international"), {"role": "operative", "lead_verb": "calls", "para": 5})
    assert got.label == "binding" and "Namibia" in got.reason
    other_para = label_for(res276, Forum("international"), {"role": "operative", "lead_verb": "requests", "para": 3})
    assert other_para.label == "recommendatory"


def test_unsc_without_paragraph_is_unknown():
    assert label_for(UNSC, Forum("international")).label == "unknown"


def test_pcij_article_59():
    assert label_for(PCIJ, Forum("international", matter_id="MTR-2")).label == "persuasive"
    assert label_for(PCIJ, Forum("international", matter_id="MTR-1")).label == "binding"  # res judicata
    assert label_for({**PCIJ, "kind": "advisory_opinion"}, Forum("international")).label == "not_binding"
    assert label_for({**PCIJ, "role": "dissent"}, Forum("international", matter_id="MTR-1")).label == "not_binding"


def test_india_hierarchy():
    cerc = forum_from_matter({"jurisdiction": "India", "court": "Central Electricity Regulatory Commission"})
    sc = {"legal_system": "india", "kind": "case", "court": "Supreme Court of India"}
    aptel = {"legal_system": "india", "kind": "case", "court": "Appellate Tribunal for Electricity"}
    other = {"legal_system": "india", "kind": "case", "court": "Punjab State Electricity Regulatory Commission"}
    assert label_for(sc, cerc).label == "binding"
    assert label_for(aptel, cerc).label == "binding"
    assert label_for(other, cerc).label == "persuasive"
    assert label_for({"legal_system": "india", "kind": "statute"}, cerc).label == "binding"


# --- formatting and OCR matching --------------------------------------------

def test_formatter_uses_metadata_and_marks_pdf_pages():
    pcij = {"provider_kind": "pcij", "case_name": "Oscar Chinn", "kind": "case", "decision_date": "1934-12-12",
            "citation": {"series": "A/B", "number": 63}, "role": "dissent", "judge": "M. ALTAMIRA"}
    assert format_citation(pcij, page=4) == (
        "*Oscar Chinn*, Judgment, 12 December 1934, P.C.I.J., Series A/B, No. 63 "
        "(Dissenting Opinion of M. Altamira), PDF p. 4")
    unsc = {"provider_kind": "unsc", "decision_date": "2001-09-28", "citation": {"number": 1373, "year": 2001}}
    assert format_citation(unsc, para=1) == "S/RES/1373 (2001), 28 September 2001, para. 1"
    assert judge_name("MM. ANZILOTTI AND HUBER") == "MM. Anzilotti and Huber"


def test_ocr_tolerant_quote_location():
    source = "DISSENTING OPINION.\n1 regret that 1 cannot concur either in the decision reached in the foregoing jiidgment"
    hit = locate_ocr(source, "I regret that I cannot concur either in the decision reached in the foregoing judgment")
    assert hit is not None and hit[2] >= 0.85
    assert locate_ocr(source, "The Court unanimously upholds the claim for compensation in full") is None
