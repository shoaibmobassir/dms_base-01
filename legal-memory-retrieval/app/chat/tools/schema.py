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
            "Read the full text content of an available document. Always call "
            "this before answering questions about, summarising, citing from, "
            "or editing a document, but call it at most once per document in a "
            "single response."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "The document ID to read (e.g. 'doc-0', 'doc-1').",
                },
            },
            "required": ["doc_id"],
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
            "copied verbatim from the document with new wording, and gives a short reason."
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
            "List all workflows available to the user. Returns each workflow's "
            "ID and title."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

READ_WORKFLOW = {
    "type": "function",
    "function": {
        "name": "read_workflow",
        "description": (
            "Read the full instructions (prompt) of a workflow by its ID."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "The workflow ID to read."},
            },
            "required": ["workflow_id"],
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
    FETCH_DOCUMENTS,
    FIND_IN_DOCUMENT,
    GENERATE_DOCX,
    GENERATE_EXCEL,
    ASK_INPUTS,
    PROPOSE_EDITS,
]

WORKFLOW_TOOLS = [LIST_WORKFLOWS, READ_WORKFLOW]

ALL_TOOLS = CORE_TOOLS + WORKFLOW_TOOLS
