"""
Tool schemas: OpenAI-compatible function-calling tool definitions for the
chat assistant agent. Clean-room independent implementation.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Document tools
# ---------------------------------------------------------------------------

READ_DOCUMENT = {
    "type": "function",
    "function": {
        "name": "read_document",
        "description": (
            "Read an available document before answering about, summarising, citing from or editing it. "
            "A short document comes back whole (complete=true). A long one comes back as its outline plus "
            "the opening part (complete=false): then read only the parts you need with section_id (from the "
            "outline) or pages, and continue a long part with next_cursor. Do not re-read a part you already have."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "The document ID to read (e.g. 'doc-0', 'doc-1').",
                },
                "section_id": {"type": "string", "description": "A section id from the outline (e.g. 's7')."},
                "pages": {"type": "string", "description": "A page or page range, e.g. '12' or '12-18'."},
                "cursor": {"type": "integer", "description": "next_cursor from the previous read of this part."},
            },
            "required": ["doc_id"],
        },
    },
}

GET_OUTLINE = {
    "type": "function",
    "function": {
        "name": "get_outline",
        "description": (
            "Get a document's table of contents: section ids, titles, page ranges and sizes, without the text. "
            "Use it to plan which parts of a long document to read or edit."
        ),
        "parameters": {
            "type": "object",
            "properties": {"doc_id": {"type": "string", "description": "The document ID (e.g. 'doc-0')."}},
            "required": ["doc_id"],
        },
    },
}

REVIEW_DOCUMENTS = {
    "type": "function",
    "function": {
        "name": "review_documents",
        "description": (
            "Answer the same questions for many documents at once (up to 500): one row per document with a short "
            "answer and the verified quote it rests on. Use it instead of reading documents one by one whenever "
            "more than about five documents need the same check (e.g. 'governing law of every contract', "
            "'which filings mention X'). Give doc_ids, or a matter, or neither to use every document in this "
            "conversation. mode='screen' ranks documents by relevance without reading them (fast)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {"type": "array", "items": {"type": "string"}, "description": "1–10 questions asked of every document."},
                "doc_ids": {"type": "array", "items": {"type": "string"}, "description": "Document IDs (e.g. ['doc-0','doc-3'])."},
                "matter": {"type": "string", "description": "A matter code or id: review all of its documents."},
                "mode": {"type": "string", "enum": ["full", "screen"]},
            },
            "required": ["questions"],
        },
    },
}

EDIT_DOCUMENT = {
    "type": "function",
    "function": {
        "name": "edit_document",
        "description": (
            "Make a change throughout one document of any length, from a plain instruction (e.g. 'rename Supplier "
            "to Vendor everywhere', 'change every payment period to 45 days', 'delete Schedule 3', 'after clause "
            "12.4 insert: ...'). It finds every paragraph concerned without you reading the whole document, and "
            "returns the edits as cards the lawyer accepts or rejects. Prefer it over propose_edits for any change "
            "that may touch more than a few places, inserts or deletes paragraphs, or concerns a long document. "
            "Quote exact wording to insert; say what must NOT change. It reads the paragraphs itself: state the change "
            "in plain terms (e.g. 'renumber the top-level headings consecutively from 1'), not a list of numbers or "
            "wording you have not read in this turn."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string", "description": "The document ID (e.g. 'doc-0')."},
                "instruction": {"type": "string", "description": "The change, stated fully and precisely."},
            },
            "required": ["doc_id", "instruction"],
        },
    },
}

COMMENT_ON_DOCUMENT = {
    "type": "function",
    "function": {
        "name": "comment_on_document",
        "description": (
            "Leave comments on passages of a document, as a colleague would when reviewing it. Each comment is "
            "anchored to an exact quote. Use it when the user asks you to review, flag, annotate or comment on a "
            "document (risks, ambiguities, missing terms, points to confirm). The comments appear on the document "
            "for everyone who can read it. To change wording instead, use edit_document or propose_edits."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string", "description": "The document ID (e.g. 'doc-0')."},
                "comments": {
                    "type": "array",
                    "maxItems": 25,
                    "items": {
                        "type": "object",
                        "properties": {
                            "quote": {"type": "string", "description": "Exact wording from the document the comment is about (a sentence or clause)."},
                            "comment": {"type": "string", "description": "The comment: what to check or change and why. Plain, specific, a few sentences at most."},
                        },
                        "required": ["quote", "comment"],
                    },
                },
            },
            "required": ["doc_id", "comments"],
        },
    },
}

FETCH_DOCUMENTS = {
    "type": "function",
    "function": {
        "name": "fetch_documents",
        "description": (
            "Read the full text content of multiple documents in a single call. "
            "Use this instead of calling read_document repeatedly when you need "
            "to read several documents at once."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doc_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Array of document IDs to read (e.g. ['doc-0', 'doc-2']).",
                },
            },
            "required": ["doc_ids"],
        },
    },
}

FIND_IN_DOCUMENT = {
    "type": "function",
    "function": {
        "name": "find_in_document",
        "description": (
            "Search for specific strings inside a document — a Ctrl+F equivalent. "
            "Returns each match with surrounding context so you can locate and "
            "quote the exact text without reading the whole document. Matching "
            "is case-insensitive and whitespace-tolerant."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "The document ID to search (e.g. 'doc-0').",
                },
                "query": {
                    "type": "string",
                    "description": "The string to search for. Case-insensitive.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum matches to return (default 20).",
                },
                "context_chars": {
                    "type": "integer",
                    "description": "Chars of context on each side of a match (default 80).",
                },
            },
            "required": ["doc_id", "query"],
        },
    },
}

SEARCH_FIRM_RECORDS = {
    "type": "function",
    "function": {
        "name": "search_firm_records",
        "description": (
            "Search the firm's document corpus for similar matters, precedents, "
            "and passages. Use this when the user asks what the firm has done "
            "before, which documents are similar, or when available documents "
            "are missing the needed evidence. Returns ranked snippets plus "
            "chat-local doc_id labels you can then read."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query.",
                },
                "k": {
                    "type": "integer",
                    "description": "Maximum documents to return (default 8).",
                },
            },
            "required": ["query"],
        },
    },
}

# ---------------------------------------------------------------------------
# Generation tools
# ---------------------------------------------------------------------------

GENERATE_DOCX = {
    "type": "function",
    "function": {
        "name": "generate_docx",
        "description": (
            "Generate a Word (.docx) document from structured content. Use this "
            "when the user asks you to draft, create, or produce a legal document. "
            "Returns a download URL for the generated file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Document title (used as filename and heading).",
                },
                "sections": {
                    "type": "array",
                    "description": "List of document sections.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "heading": {"type": "string", "description": "Optional section heading."},
                            "level": {"type": "integer", "description": "Heading level: 1, 2, or 3."},
                            "content": {
                                "type": "string",
                                "description": "Prose text content (paragraphs separated by double newlines).",
                            },
                            "pageBreak": {
                                "type": "boolean",
                                "description": "Start this section on a new page.",
                            },
                        },
                    },
                },
            },
            "required": ["title", "sections"],
        },
    },
}

GENERATE_EXCEL = {
    "type": "function",
    "function": {
        "name": "generate_excel",
        "description": (
            "Generate an Excel (.xlsx) workbook from structured sheet data. "
            "Use when the user asks for a spreadsheet, tracker, or Excel file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Workbook title, used as filename."},
                "sheets": {
                    "type": "array",
                    "description": "Workbook sheets with name, columns, and rows.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Sheet tab name."},
                            "columns": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Column header labels.",
                            },
                            "rows": {
                                "type": "array",
                                "items": {"type": "array", "items": {"type": "string"}},
                                "description": "Array of rows.",
                            },
                        },
                        "required": ["name", "columns", "rows"],
                    },
                },
            },
            "required": ["title", "sheets"],
        },
    },
}

# ---------------------------------------------------------------------------
# Interaction tools
# ---------------------------------------------------------------------------

ASK_INPUTS = {
    "type": "function",
    "function": {
        "name": "ask_inputs",
        "description": (
            "Ask the user for one or more decisions, open-ended answers, "
            "clarifications, or document uploads before continuing. Use when "
            "guessing would materially affect the answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 12,
                    "description": "The list of user inputs needed.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Stable short ID for this input.",
                            },
                            "kind": {
                                "type": "string",
                                "enum": ["choice", "text", "documents"],
                            },
                            "question": {
                                "type": "string",
                                "description": "The question to show to the user.",
                            },
                            "options": {
                                "type": "array",
                                "description": "For choice items: selectable choices.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "value": {"type": "string"},
                                    },
                                    "required": ["value"],
                                },
                            },
                        },
                        "required": ["id", "kind"],
                    },
                },
            },
            "required": ["items"],
        },
    },
}


PROPOSE_EDITS = {
    "type": "function",
    "function": {
        "name": "propose_edits",
        "description": (
            "Suggest specific changes to one document for the lawyer to accept or "
            "reject. Read the document first. Each edit replaces an exact passage "
            "copied verbatim from the document with new wording, and gives a short reason. "
            "Suggest changes of substance only. Never suggest fixing spacing, line breaks, hyphenation or "
            "single-letter spelling in text that came from a PDF (especially scanned pages): that text was "
            "machine-read and those differences are not mistakes in the document; such suggestions are dropped."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string", "description": "The document to edit (e.g. 'doc-0')."},
                "edits": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 20,
                    "items": {
                        "type": "object",
                        "properties": {
                            "original": {
                                "type": "string",
                                "description": "Exact passage from the document to replace. Copy it verbatim; do not include [Page N] markers.",
                            },
                            "proposed": {
                                "type": "string",
                                "description": "Replacement wording. Empty string to delete the passage.",
                            },
                            "reason": {"type": "string", "description": "One sentence on why."},
                        },
                        "required": ["original", "proposed", "reason"],
                    },
                },
            },
            "required": ["doc_id", "edits"],
        },
    },
}


# ---------------------------------------------------------------------------
# Firm knowledge tools (Ask the Firm layer)
# ---------------------------------------------------------------------------

ASK_FIRM = {
    "type": "function",
    "function": {
        "name": "ask_firm",
        "description": (
            "Ask the firm's knowledge desk a question about the firm's own matters, clients, "
            "documents or people (e.g. 'what is the long stop date?', 'who led our work on X?', "
            "'which matters have we handled for Acme?'). Resolves the matter, reads the matter "
            "record, team and the most relevant passages, and returns a draft answer plus "
            "verbatim passages (with doc-N labels) you can quote and cite. Prefer this over "
            "search_firm_records for factual questions about firm matters."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question in plain language."},
                "scope": {
                    "type": "string",
                    "description": "Optional matter code, matter id, matter title or client name to limit the question to.",
                },
            },
            "required": ["question"],
        },
    },
}

RESOLVE_MATTER = {
    "type": "function",
    "function": {
        "name": "resolve_matter",
        "description": (
            "Identify which firm matter a description refers to (parties, subject, facts, "
            "code or title), e.g. 'the series B deal where the seed investor sold its shares'. "
            "Returns the resolved matter or ranked candidates with confidence."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Description of the matter."}},
            "required": ["query"],
        },
    },
}

GET_MATTER_PROFILE = {
    "type": "function",
    "function": {
        "name": "get_matter_profile",
        "description": (
            "Get a matter's full record: parties, facts, legal issues, status, forum, team with "
            "roles, open deadlines and its documents (as doc-N labels you can read)."
        ),
        "parameters": {
            "type": "object",
            "properties": {"matter": {"type": "string", "description": "Matter code, matter id or title."}},
            "required": ["matter"],
        },
    },
}

FIND_PEOPLE = {
    "type": "function",
    "function": {
        "name": "find_people",
        "description": (
            "Find firm members: the team on a matter (pass `matter`), or people with expertise, "
            "a role or an office (pass `query`, e.g. 'expert in boundary disputes', 'partner in Delhi')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Expertise, role or office to look for."},
                "matter": {"type": "string", "description": "Matter code, id or title to list its team."},
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Workflow tools
# ---------------------------------------------------------------------------

LIST_WORKFLOWS = {
    "type": "function",
    "function": {
        "name": "list_workflows",
        "description": (
            "List the playbooks available to the user (the firm's ways of doing a job: shipped, published by the "
            "firm, and the user's own). Each has an id, title, summary and kind (instructions, or a set of review "
            "columns)."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

READ_WORKFLOW = {
    "type": "function",
    "function": {
        "name": "read_workflow",
        "description": (
            "Read a playbook by its id before doing the job it describes, then follow it: ask for missing inputs, "
            "open its reference documents, and do the steps. A columns playbook is a set of review questions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "The playbook id (PBK-…) to read."},
            },
            "required": ["workflow_id"],
        },
    },
}


# ---------------------------------------------------------------------------
# Legal research tools (authorities: PCIJ decisions, UN Security Council resolutions)
# ---------------------------------------------------------------------------

_LEGAL_SYSTEM = {
    "type": "string",
    "description": "Legal system of the forum when it differs from the conversation's matter: 'international' or 'india'.",
}

SEARCH_AUTHORITY = {
    "type": "function",
    "function": {
        "name": "search_authority",
        "description": (
            "Search legal authorities: decisions of the Permanent Court of International Justice (judgments, "
            "orders, advisory opinions) and UN Security Council resolutions. Use for questions about what the law "
            "is, what a court held or what the Council decided, as opposed to facts in the firm's files "
            "(use ask_firm for those). Each result has a doc-N label, its citation, the matching passage's role "
            "(operative paragraph, preamble, majority, dissent...) and a binding label with its reason. Run "
            "several searches in one round for different issues or angles."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The legal issue in plain words, or a citation."},
                "kinds": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["case", "advisory_opinion", "order", "resolution"]},
                    "description": "Limit to these kinds of authority.",
                },
                "date_from": {"type": "string", "description": "Earliest decision date, YYYY-MM-DD."},
                "date_to": {"type": "string", "description": "Latest decision date, YYYY-MM-DD (the as-of date of the question)."},
                "legal_system": _LEGAL_SYSTEM,
                "limit": {"type": "integer", "description": "Results to return (default 6, max 12)."},
            },
            "required": ["query"],
        },
    },
}

READ_AUTHORITY = {
    "type": "function",
    "function": {
        "name": "read_authority",
        "description": (
            "Read an authority before citing it. A resolution comes back as its operative paragraphs, each with "
            "its binding label, plus a list of preambular paragraphs. A PCIJ decision comes back page by page "
            "with [Page N] markers (PDF pages); continue with next_cursor or ask for pages. Says when the text is "
            "a judge's dissent or separate opinion rather than the Court's decision."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "authority": {"type": "string", "description": "A doc-N label from search_authority, or a citation."},
                "paras": {"type": "string", "description": "Resolution operative paragraphs to return, e.g. '1-3,6'."},
                "pages": {"type": "string", "description": "PCIJ decision pages, e.g. '12' or '12-15'."},
                "cursor": {"type": "integer", "description": "next_cursor from the previous read."},
                "legal_system": _LEGAL_SYSTEM,
            },
            "required": ["authority"],
        },
    },
}

RESOLVE_CITATION = {
    "type": "function",
    "function": {
        "name": "resolve_citation",
        "description": (
            "Check that a citation exists and find the authority it refers to, e.g. 'S/RES/1373 (2001)', "
            "'P.C.I.J., Series A, No. 1'. Use it for any authority you recall from memory before relying on it: "
            "an authority that does not resolve must not be cited."
        ),
        "parameters": {
            "type": "object",
            "properties": {"citation": {"type": "string", "description": "One or more citations."}},
            "required": ["citation"],
        },
    },
}

GET_CITING_AUTHORITIES = {
    "type": "function",
    "function": {
        "name": "get_citing_authorities",
        "description": (
            "Later authorities that cite this one, with how they treat it (extended, terminated, superseded, "
            "applied, recalled), derived from their text. Use it to find later developments before relying on "
            "an older resolution or decision."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "authority": {"type": "string", "description": "A doc-N label or a citation."},
                "limit": {"type": "integer", "description": "Maximum results (default 15)."},
            },
            "required": ["authority"],
        },
    },
}

CHECK_AUTHORITY_STATUS = {
    "type": "function",
    "function": {
        "name": "check_authority_status",
        "description": (
            "Status of an authority as of a date: expired or terminated (with the later resolution that did it), "
            "caution, or 'status not verified' when nothing is known. Check every authority you cite."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "authority": {"type": "string", "description": "A doc-N label or a citation."},
                "as_of": {"type": "string", "description": "Date the answer speaks to, YYYY-MM-DD (default today)."},
            },
            "required": ["authority"],
        },
    },
}

VERIFY_CITATIONS = {
    "type": "function",
    "function": {
        "name": "verify_citations",
        "description": (
            "Cite-check a passage or a whole document: for every citation, whether it exists, whether its "
            "pinpoint (page or paragraph) is real, whether a quote placed before it is in the authority and in "
            "the Court's or Council's own text, its status and its binding label. Citations to sources the firm "
            "does not hold (Indian, ICJ, US) are reported as recognized but not verified."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to check."},
                "doc_id": {"type": "string", "description": "Or a doc-N label of a document to check."},
                "as_of": {"type": "string", "description": "Status date, YYYY-MM-DD."},
                "legal_system": _LEGAL_SYSTEM,
            },
        },
    },
}

SEARCH_WORKSPACE = {
    "type": "function",
    "function": {
        "name": "search_workspace",
        "description": (
            "Find words inside the documents of this conversation's workspace (a project, matter or the user's "
            "library), including documents that firm-wide search does not cover. Returns documents with the page "
            "and passage that matched; read them with read_document."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words or a phrase to find."},
                "limit": {"type": "integer", "description": "At most this many documents (default 10)."},
            },
            "required": ["query"],
        },
    },
}

FIND_PRECEDENTS = {
    "type": "function",
    "function": {
        "name": "find_precedents",
        "description": (
            "Find the firm's precedents for a clause: the closest passages in the firm's template library and in "
            "documents on the firm's matters (never personal libraries or projects), by meaning. Use it when the user "
            "asks how a clause compares with what the firm has used before, then compare point by point and cite."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The clause text to compare, verbatim."},
                "document": {"type": "string", "description": "The doc-N label or DOC id the clause comes from (left out of the results)."},
                "limit": {"type": "integer", "description": "At most this many documents (default 6, at most 10)."},
            },
            "required": ["text"],
        },
    },
}

READ_REVIEW_CELLS = {
    "type": "function",
    "function": {
        "name": "read_review_cells",
        "description": (
            "Read a tabular review (documents × questions) the user has open or names: each answer with its quoted "
            "passage and page. Use it to summarise, compare or find gaps across the documents instead of re-reading them."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "review_id": {"type": "string", "description": "The review's id (TRV-…)."},
                "row_ids": {"type": "array", "items": {"type": "string"}, "description": "Only these rows (optional)."},
                "column_ids": {"type": "array", "items": {"type": "string"}, "description": "Only these columns (optional)."},
            },
            "required": ["review_id"],
        },
    },
}

# ---------------------------------------------------------------------------
# Composite tool sets
# ---------------------------------------------------------------------------

CORE_TOOLS = [
    ASK_FIRM,
    RESOLVE_MATTER,
    GET_MATTER_PROFILE,
    FIND_PEOPLE,
    SEARCH_FIRM_RECORDS,
    READ_DOCUMENT,
    GET_OUTLINE,
    REVIEW_DOCUMENTS,
    EDIT_DOCUMENT,
    COMMENT_ON_DOCUMENT,
    FETCH_DOCUMENTS,
    FIND_IN_DOCUMENT,
    GENERATE_DOCX,
    GENERATE_EXCEL,
    ASK_INPUTS,
    PROPOSE_EDITS,
    FIND_PRECEDENTS,
]

WORKFLOW_TOOLS = [LIST_WORKFLOWS, READ_WORKFLOW]

RESEARCH_TOOLS = [
    SEARCH_AUTHORITY,
    READ_AUTHORITY,
    RESOLVE_CITATION,
    GET_CITING_AUTHORITIES,
    CHECK_AUTHORITY_STATUS,
    VERIFY_CITATIONS,
]

WORKSPACE_TOOLS = [SEARCH_WORKSPACE, READ_REVIEW_CELLS]

ALL_TOOLS = CORE_TOOLS + RESEARCH_TOOLS + WORKFLOW_TOOLS + WORKSPACE_TOOLS
