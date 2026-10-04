# 09 Entity lifecycle and ingestion plan

Status: plan, executed in order below (see "Delivery log" at the end).
Scope: how a matter is opened, worked, resolved (closed) and reopened; how people are put on a matter; the same for clients,
people and arguments; and how data gets into the firm (documents, folders, spreadsheets). Product rules from `PRODUCT.md`:
the person always chooses (nothing is defaulted), every change is audited, access is enforced on the server.

## 1. What exists today (verified in code)

| Area | Backend | Interface |
|---|---|---|
| Matter | create, update fields (including `status` Open / On hold / Closed, `outcome`, `closed_date` set automatically), pin | New matter dialog; Edit dialog with a status box. No dedicated "close" step, no check of what is still open, no reopen. |
| Matter team | add or change (`PUT staff`), remove; one lead is always kept; screened people are refused | Team editor on the People tab (a plain dropdown of everyone). |
| Timeline, arguments, related matters | full create, edit, delete | On the matter page. |
| Argument bank | read | Read-only page. Arguments can only be added from inside a matter. |
| Client | create after a conflict check; no update, no notes write, no close | New client dialog and conflict queue. Client page is read-only. |
| Person | create (admin), patch (admin), patch self | Admin "Add a person", "Edit my expertise". No admin edit of another person, no deactivate. |
| Documents in | single ingest (text), upload batches (several files, `relative_paths` supported), ingest jobs from a server folder | Documents page upload (files or pasted text). No folder upload, no progress list, no spreadsheet import. |
| Documents out | download, versions, privacy | No archive or delete. |
| Security note | `POST /api/documents/ingest/jobs` takes a server folder path and has no permission check | Must be limited to administrators. |

## 2. Lifecycle rules

**Matter.** Open, On hold, Closed. *Resolving* a matter means closing it with an outcome.
- Closing shows what is still open (court dates not done, unconfirmed court dates, pending access requests) and needs an outcome.
  Open court dates can be marked done in the same step, or the close is blocked until they are handled.
- A closed matter shows a banner with the outcome and who closed it, and offers Reopen (with a reason, audited).
- Only people with manage level on the matter can close or reopen.

**Team.** Add a person by searching (never a 200-item list), choose role and start date; remove asks first; "make lead" swaps
the lead in one step. The server already keeps one lead and refuses screened people; the interface explains those refusals.

**Client.** Statuses: prospective (conflict check pending), active, on hold, inactive. A client can be edited and given notes
(prefers, avoid, terms). Making a client inactive is blocked while it has open matters. "New matter for this client" starts the
matter dialog with the client chosen.

**Person.** An administrator edits another person (title, office, practice areas, email, roles) and can deactivate or reactivate
them. A deactivated person disappears from pickers and cannot be staffed on new matters; their history stays.

**Argument.** The bank page can record an argument: choose the matter first, then the usual form. Edit and delete appear in the
detail pane for people who may edit that matter.

## 3. Ingestion

1. Guard the folder-ingest endpoint (administrators only) and test it.
2. Upload a folder (keeps the folder names), several files at once (done), progress per file (done).
3. Import spreadsheets (CSV) for clients, people and matters: download a template, validate first (nothing saved), then apply.
   Rows with problems are listed with the reason; the rest can still be applied. Administrators only; audited.
4. A "recent uploads" list on the Documents page (batch, files, indexed, duplicates, failed) with retry of failed files.
5. Archive a document (soft delete, hidden from lists and search, restorable by an administrator). Never a hard delete from the
   interface.

## 4. Order of work

| # | Item | Notes |
|---|---|---|
| 1 | Close and reopen a matter | `close-check`, `close`, `reopen` endpoints; dialog; banner; tests |
| 2 | Team editor: add by search, make lead, remove with confirmation | uses the existing staffing API |
| 3 | Guard folder ingest; upload a folder | security first |
| 4 | Clients: edit, notes, inactive, new matter for client | new backend functions and endpoints |
| 5 | People: admin edit, deactivate and reactivate | `members.active` if the column exists, else add it |
| 6 | Arguments: record from the bank, edit and delete in the pane | frontend only |
| 7 | CSV import (dry run, then apply) | admin page `/admin/import` |
| 8 | Recent uploads and retry | list endpoint for the caller's batches |
| 9 | Archive and restore a document | soft delete with audit |

Each item ends with backend tests where there is backend code, a Playwright check, and an entry below.

## 5. Delivery log

All nine items are delivered. Each has backend tests where there is backend code and a Playwright check.

| # | Delivered | Where |
|---|---|---|
| 1 | Close check, close with outcome, reopen with reason; banner | `app/firm/matters.py`, `tests/test_matter_lifecycle.py`, `MatterEditors.tsx` |
| 2 | Team editor: search to add, make lead, confirm remove; inactive people refused | `MatterEditors.tsx` |
| 3 | Folder ingest limited to `integrations.manage`; folder upload keeps folder names | `documents_router.py`, `uploads.ts` |
| 4 | Client edit, notes, on hold / inactive (blocked by open matters), new matter for client | `app/firm/clients.py`, `tests/test_client_lifecycle.py` |
| 5 | Admin edits a person; deactivate and reactivate (`members.active`) | `app/firm/people.py`, `tests/test_person_lifecycle.py` |
| 6 | Record an argument from the bank; edit and delete in the pane | `ArgumentsPage.tsx` |
| 7 | CSV import for clients, people, matters: template, check first (saves nothing), apply; row reasons; clients with possible conflicts left for the conflict queue; audited `import.apply` | `app/firm/imports.py`, `tests/test_csv_import.py`, Admin "Import" tab |
| 8 | "Your recent uploads" on Documents with per-file outcome and retry of failed files | `GET /api/uploads/batches`, `tests/test_recent_uploads.py`, `RecentUploads.tsx` |
| 9 | Archive a document (manage access, reason required); hidden from lists, search, retrieval, Assistant and direct links; administrator restores from Admin "Archive" | migration `20261003d`, `app/documents/archive.py`, `tests/test_document_privacy.py` |

Decisions: archiving compiles an empty visibility list (so every existing read path hides it with no new filter) and
`document_access` returns "none" for archived documents. Restore and the archive list need `users.manage`. There is still no
hard delete in the interface.

