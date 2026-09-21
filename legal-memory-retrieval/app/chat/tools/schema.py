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
    SEARCH_FIRM_RECORDS,
    READ_DOCUMENT,
    FETCH_DOCUMENTS,
    FIND_IN_DOCUMENT,
    GENERATE_DOCX,
    GENERATE_EXCEL,
    ASK_INPUTS,
]

WORKFLOW_TOOLS = [LIST_WORKFLOWS, READ_WORKFLOW]

ALL_TOOLS = CORE_TOOLS + WORKFLOW_TOOLS
