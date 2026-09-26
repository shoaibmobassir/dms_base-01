# 05 — Chat experience

Closes: B8, B9, B10.

## Clean-room requirements (from product research on `mike/`, no code reuse)

Observed *user-facing* capabilities, rewritten as technology-independent requirements.
Recorded in `docs/legal/IP_ORIGIN_RECORD.md`.

| # | Requirement |
|---|---|
| R1 | A lawyer can stop an answer while it is being written; the partial answer is kept. |
| R2 | The assistant shows what it is doing (searching, reading a document) as it works, collapsible after. |
| R3 | Every claim that relies on a firm document links to that document by title; opening it shows the cited passage. |
| R4 | The model is chosen from the models the firm has configured, not typed. |
| R5 | A conversation gets a short title from its first question automatically; the lawyer can rename it. |
| R6 | Past conversations are listed newest first, grouped by day, and can be deleted with confirmation. |
| R7 | Enter sends, Shift+Enter adds a line; the composer grows with its content. |
| R8 | A failed answer shows an inline error with Retry, not only a toast. |
| R9 | An answer can be copied. |
| R10 | Suggested starter questions on an empty conversation, drawn from the lawyer's own matters. |

## Backend

- `GET /api/chat/models` → configured providers/models from `app/llm/model_router.py` + default.
- `POST /sessions` with no title → `title = null` so auto-title fires (B8).
- Citation events carry `document_id`, `title`, `chunk_id`, `snippet`.
- Client disconnect (stop) → generator closes; partial text is persisted with `status: "stopped"`.
- Starter questions: `GET /api/chat/suggestions` built from the caller's recent in-scope matters.

## Frontend

Rebuild `ChatPage` in the code_pre visual language (serif display, hairlines, wine accent):
left rail (sessions by day), centre thread, right source panel (`SourceViewer`) when a citation is
opened. `AbortController` for stop. Markdown rendering for answers.

## Done when

- R1–R10 demonstrably work against the seeded DB (06 adds API tests for R1/R4/R5 and ownership).
