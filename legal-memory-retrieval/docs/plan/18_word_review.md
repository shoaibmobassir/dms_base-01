# Plan 18 — Word-style review: who changed what, accept/reject, comments both ways

Started 2026-09-28. Status keys: `[ ]` open · `[~]` in progress · `[x]` done (with date + evidence).

Prompted by two real multi-reviewer Word files in `../docs/` (ISTS waiver petition: 3 reviewers, 78 tracked
revisions, 21 comments incl. 9 replies; SGIPL CERC infirm power: 6 reviewers, 867 revisions incl. 129 formatting
changes and moves, 48 comments incl. 24 replies). Decisions (product owner, 2026-09-28): other reviewers' pending
changes are preserved — a paragraph holding them is accepted/rejected before it can be edited in the browser;
comments flow both ways between Word and Precentis.

Gaps found: `accept_all` ignores moves (moved text duplicated in our text/search); a browser save accepted every
pending change of every reviewer; Word comments not imported, ours never exported; no per-person view.

- [ ] R1 `app/documents/docx_review.py`: read every revision (author, date, type, text, paragraph), group like
      Word's reviewing pane; accept/reject any set (moves, formatting, paragraph marks, table rows);
      accept/reject everything; final/original text; contributors.
- [ ] R2 `document_revision_authors`; review + contributors API; Final / Markup / Original renditions.
- [ ] R3 Accept/reject in Precentis → attributed new version; Review panel.
- [ ] R4 Editor keeps others' pending changes; paragraphs with others' changes locked; own changes re-editable.
- [ ] R5 `app/documents/docx_comments.py`: import Word comments/replies/resolved; export Precentis comments,
      replies and resolution into the .docx (save, review, download).
- [ ] Tests, eval on the two real files, Playwright, docs.

## Log

- 2026-09-28 — Plan written from a read-only analysis of the two files and our code.
