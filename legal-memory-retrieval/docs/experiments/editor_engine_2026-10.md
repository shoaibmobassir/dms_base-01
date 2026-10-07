# Editor engine for full-fidelity Word editing (plan 22, X1) — 2026-10-07

**Question.** Our browser editor (TipTap over a paragraph model, tracked changes written by the server) cannot edit
tables, headers and footers or footnotes (plan 16 "Known v1 limits"). Which engine should edit them, keeping exact
fidelity and server-decided authorship?

**Options.** (a) keep the paragraph model and add table-cell editing; (b) Folio (`@stll/folio-core` / `folio-react`,
Apache-2.0), a ProseMirror .docx engine that models and writes the whole package; (c) Collabora Online over WOPI.

**Method.** Ten files: the two real filings in `docs/` (one with 21 comments, 4 tables, 74 tracked changes; one with
48 comments and 514 tracked changes), generated 10/100/400-page agreements with a table, and five held-out files from
the object store (one with someone else's tracked changes). For each: open; save with no edits; tracked edits in a
body paragraph and in a table cell; a separate fixture with a footnote and a header edited as stories. Checked with
*our* tools (`evals/editor_engine/validate.py`): every story's text, revision and comment counts, the new revisions'
author, accept-all and reject-ours text, LibreOffice render (Gotenberg). Harness and results: `evals/editor_engine/`.

**Results (Folio 0.55 core).**

| Check | Result |
|---|---|
| Round-trip text identical (body, tables, headers, footers, notes, comments) | 10/10 |
| Round-trip revision and comment counts identical | 10/10 |
| Tracked edit in a paragraph: authored, accept correct, reject restores | 7/7 files with prose |
| Tracked edit in a table cell | 4/4 files with tables |
| Footnote and header edited as tracked changes; accept/reject; render | pass |
| Others' tracked changes and comments kept after our edit | 10/10 |
| LibreOffice renders the edited file | 10/10 |
| Open (parse + snapshot), 400 pages | 0.40 s (gate < 3 s) |
| Edit + save, 400 pages | 0.67 s (our current save p95 2.2–2.3 s) |

Collabora (c) was not measured: it needs its own server container, which is not part of this environment; it stays the
later "open in full editor" option of plan 16 E7. Option (a) fails the capability gate by construction (tables,
headers/footers and footnotes are not in its model).

**Decision.** Adopt Folio as the full Word editor (W2b), behind our existing lock / version / compare / history APIs:
the browser editor (`folio-react`, tracked changes on by default) sends the edited .docx to
`POST /api/editor/documents/{id}/save-docx`; the server **re-stamps every revision that was not in the base version
with the signed-in member and its own clock** (`app/documents/docx_restamp.py`), stores the clean version as every save
does, and records who changed what. The paragraph editor stays at `/documents/:id/edit` (plan 16–21 flows and tests);
the Word editor is `/documents/:id/write` and a workbench tab.

**Risks and follow-ups.** Folio is young (v0.x, weekly releases, ~30 GitHub stars): versions are pinned exactly and
upgrades go through this harness. The editor bundle is 2.1 MB (635 KB gzip), loaded only when the editor opens. In one
of four live runs, keystrokes typed immediately after the editor appeared were saved untracked; the later runs tracked
correctly — watch for a mode race at first paint. Licences: `docs/legal/DEPENDENCY_AUDIT.md`.
