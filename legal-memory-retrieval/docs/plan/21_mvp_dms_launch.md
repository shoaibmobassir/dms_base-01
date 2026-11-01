# 21 — MVP launch plan: a matter-centric DMS with "Ask the Firm" (find-only)

Status: draft v3 for review · Date: 2026-10-09 (v1 2026-10-08, v2 2026-10-09)
Proposed branch: `mvp/dms-core` (cut from the last stable integration point; see §10)

v2 changes: exhaustive feature log (Appendix A) built from the "iManage & NetDocuments Feature Guide" PDF,
the pasted iManage Work 10 vs NetDocuments architecture report, and a further web sweep; email/Outlook
capture moved into MVP via server-side sync (no add-in needed); matter and document profile field lists
(Appendix B); India-specific needs (Appendix C).

v3 changes: Appendix A rebuilt as a granular catalog (every action, menu item, option, indicator, limit and
rule found in vendor help pages); new appendices D–J: step-by-step user journeys, icons and states, limits and
defaults, role × action permission matrix, settings catalog, notifications catalog, audit event catalog.
Module text (§4) updated with copy/move/file semantics, mail-folder options, wall policy types, guest upload
requests, search operators, disposition review levels.

---

## 1. Goal and non-goals

### Goal
Ship a law-firm document management system that does what a lawyer expects from
iManage Work or NetDocuments: every document, email, and note lives in a **matter**,
carries a **profile** (metadata), is **versioned**, **permissioned** (ethical walls),
**audited**, **searchable**, and subject to **retention / legal hold**. On top of that,
one AI feature: **Ask the Firm**, which only *finds and cites* relevant material
for a matter. It does not draft, edit, or summarise beyond what is needed to show the
answer with citations.

### Non-goals (cut from the MVP branch, kept on other branches)
- Assistant / chat agent, tool-calling, memory
- AI editing, redlining, drafting, rewrite-in-document
- Tabular review, playbooks, workflows, citation verification products
- Word-in-browser editor (`FullWordEditor`); users edit in desktop Word and check back in
- Real-time co-authoring
- No-code app builder / document automation
- Case-law research layer, Kafka, Neo4j (already barred by project rules)

### Success criteria (launch gate)
1. A pilot firm can onboard clients, matters, users, and bulk-load a real archive without engineering help.
2. A lawyer can find any document or email by profile fields, full-text, or Ask the Firm in under 10 s.
3. A lawyer can get email into a matter from any device (desktop, web mail, phone) without installing anything.
4. Zero cross-matter / cross-wall leaks in the permission test suite (SQL-level filter before ranking).
5. Every open/preview/download/edit/share/permission change is in an append-only audit log.
6. Ask the Firm meets the retrieval gate in §8 on the frozen eval set, and every citation resolves to a retrieved id.

---

## 2. Research: what iManage and NetDocuments actually do

Sources: public vendor docs (§12), the "iManage & NetDocuments Feature Guide" PDF in the repo root,
and the pasted iManage Work 10 vs NetDocuments architecture report. This is requirements research only;
we design our own schema, names, UI, and copy (see §11).

**Appendix A is the full, line-by-line feature log** (every feature, however small, with an MVP decision).
The table below is the summary.

### 2.1 Capability inventory (summary)

| # | Capability | iManage Work | NetDocuments | MVP? |
|---|---|---|---|---|
| 1 | **Matter workspace**: one root container per client matter holding folders, tabs, docs, emails | Workspace (root container, only at library level; may be named Matter/Project) | Workspace built on a Matter profile attribute; shared view for everyone; template-driven; "Refresh workspace" | **Yes** |
| 2 | **Workspace templates** (default folder structure per matter type) | Templates/tabs | Cabinet-admin workspace templates + auto-generated filters | **Yes** |
| 3 | **Client → Matter hierarchy**, matter key + description, open/closed/pending | Custom properties captioned Client/Matter | Lookup tables for Client/Matter attributes | **Yes** |
| 4 | **Document profile** (metadata): name, author, operator, class/subclass, doc type, status, dates, custom fields | Properties; class required, subclass optional; configurable captions | Cabinet profile attributes (standard + custom, lookup-table backed), default profile values, profile templates | **Yes** |
| 5 | **Folders, sub-folders, saved views** | Folders and tabs | Folders + "Filters" (virtual folders built from profile values) | **Yes** (folders + saved filters) |
| 6 | **Versioning**: every save is a version; restore, promote, compare, version description | Doc# + .N versions; save as new version with comment; compare; promote older version | Up to 32k versions; official version; lock versions; version description | **Yes** |
| 7 | **Check-out / check-in** (exclusive edit lock; echo/shadow copy) | Yes, red padlock | Yes (via ndOffice, Echo folder) | **Yes** (lock + upload-new-version) |
| 8 | **Security model**: public / view / private / inherited; user + group ACLs | Default security + ACL; inheritance; "apply security to contents" with exceptions | Security templates, profile-based security, ACL levels | **Yes** |
| 9 | **Ethical walls / need-to-know**: locked, non-overridable, retroactive | Security Policy Manager | Workspace Security Manager | **Yes** |
| 10 | **Email management**: file mail + attachments into matter; dedupe; thread tagging; predictive filing; linked folders; mobile filing | Outlook toolbar + Work Panel, Send-and-File with folder-ID tag, linked Outlook folders, Gmail extension | ndMail predictive filing, Outlook add-in | **Yes, server-side** (upload, filing address with thread tag, M365/Gmail folder sync). Add-in post-MVP. See M5. |
| 11 | **Full-text + metadata search**, stemming, saved searches, recents, favourites, "Go to matter" | Smart search bar, stemming, personalised ranking | Search with highlight/snippets, recent/favourite workspaces & docs | **Yes** |
| 12 | **OCR** of scans and photos | via add-on | 24/7 background OCR | **Yes** |
| 13 | **Audit trail / document history** | Timeline: edited, viewed, previewed, emailed, downloaded, printed | Activity/audit logs | **Yes** |
| 14 | **Records: declare record, retention, disposition, legal hold** | Records Manager, declare as record | Retention policies; litigation hold | **Yes** (basic) |
| 15 | **Archival (read-only) store** | Archive libraries | Archival cabinet | **Yes** (matter close → read-only) |
| 16 | **Trash / soft delete / recovery** | Personal Trash, admin restore, deletion report | Recycle | **Yes** |
| 17 | **External sharing** with expiry / password / download control | Share, secure links, iManage Share portal | Secured links, CollabSpaces | **Yes** (links). Portal post-MVP |
| 18 | **Desktop integration**: Office ribbon, mapped drive, two-way sync, echo folder | Work Desktop, Drive, ribbons, footers | ndOffice, ndSync, ndClick | **No** (post-MVP) |
| 19 | **Mass operations / migration** | Admin tools | Mass profile / access change, import | **Yes** |
| 20 | **Admin console** | Control Center | Cabinet admin | **Yes** (lean) |
| 21 | **Encryption, customer keys, SSO, MFA, residency** | Zero Trust, CMEK | 3-layer EKM, BYOK, FlexStore | **SSO + encryption at rest + India region yes**; CMEK post |
| 22 | **Integrations / automation** | Power Automate connector | PatternBuilder no-code | **No** (webhook + CSV only) |
| 23 | **Transaction / litigation bundles** | Closing Folders, Tracker | SetBuilder | **No** (first post-MVP candidate: court paper books) |
| 24 | **Internal collaboration** (chat, tasks, Teams) | Tracker | ndThread, Tasks, ChatLink | **Matter notes only** |
| 25 | **AI** | Ask iManage, Context Fabric, MCP | Smart Answers, ndMAX, PatternBuilder MAX | **Only Ask the Firm (find-only)** |

### 2.2 Baseline legal-DMS requirements (cross-vendor checklist)
Matter-centric filing · Outlook/Gmail capture · OCR full-text search · versioning with check-in/out ·
matter-level permissions and **logged** ethical walls (screened user cannot open, find, or know the doc exists) ·
access report "who had access to matter X between dates" · closure event driving retention ·
legal hold overriding schedule · human-approved disposition · audit log that survives document deletion and cannot be edited by admins ·
automatic document + version numbering · complete client-file export.

---

## 3. What already exists in this repo (reuse, do not rebuild)

| Area | Existing | Gap for MVP |
|---|---|---|
| Matters / clients / people | `app/firm/{matters,clients,people}.py`, routers `matters`, `clients`, `people`, tables `matter_profiles`, `matter_links`, `matter_events`, `conflict_checks` | Matter templates, numbering, open/close/archive lifecycle, bulk create/import UI, profile fields in Appendix B |
| Access | `matter_access`, `matter_grants`, `matter_screens`, `document_access`, `access_requests`, `role_permissions`, `app/access/refresher.py`, `doc_acl_state` | Inheritance rules, "apply to contents" tool, locked walls, two-person wall removal, access report |
| Documents/versions | `document_versions`, `document_events`, `document_locks`, `version_diffs`, `app/documents/*` | Check-out/in UX, official version, version description, restore/promote, document numbers |
| Ingest/upload | `app/ingest/*`, `upload_batches`, `upload_batch_files`, `source_connections`, `source_files` | Profile-on-upload, duplicate detection, mapping CSV, bulk migration runner, email parsing, mailbox sync connectors |
| Audit | `audit_events`, `app/audit/*`, `audit_router` | Append-only guarantees, per-document history tab, access report, export |
| Retrieval + Ask | `app/retrieval`, `app/answers`, `ask_answers`, `ask_history`, Ask router | Strip chat/agent coupling; matter-scoped "find" UI; matter-facts card |
| Archive/purge | `document_archive` migration, `app/ingest/purge.py` | Retention schedules, holds, declare-as-record, disposition workflow |
| Auth | `app/auth/*` (OIDC, sessions, API keys) | SSO onboarding + MFA guidance |

Also reusable from the `workbench` worktree: upload batch API, document workspace shell. Review each file
before pulling it in (the branch carries a lot of assistant-coupled code).

---

## 4. Product scope (modules)

Each module lists MVP behaviour. Appendix A has the item-level log with the source feature each item answers.

### M1. Firm & identity setup
- Firm profile, offices, practice areas, jurisdictions.
- Users, groups/teams, roles (Admin, Records Manager, Partner, Associate, Paralegal, Staff, Read-only, External).
- Non-interactive **service accounts** for integrations (mail sync, webhooks, migration); every action they take is audited as the service account plus the user on whose behalf it ran.
- SSO (OIDC: Microsoft Entra ID, Google Workspace) + local fallback; MFA enforced for local accounts; session timeout; deactivate user (access removed, history retained).
- Admin console: lookup tables (doc classes, statuses, matter types, practice areas, courts), configurable captions (e.g. "Matter" ↔ "Project", "Client" ↔ "Entity/Department" for in-house teams).

### M2. Clients & matters (the spine)
- Create / edit / merge clients; auto client number; related parties, contacts, notes.
- Create matter with the fields in **Appendix B.1**; matter number auto-sequenced per client (format configurable, e.g. `00042-0007`).
- Status lifecycle: Pending (intake) → Open → On Hold → Closed → Archived; every transition is a `matter_events` row.
- **Conflict check record** attached before a matter becomes Open (record + result + who cleared it; no conflict engine in MVP).
- **Matter templates**: default folder tree, default security policy, default profile values, default saved filters per matter type. "Re-apply template" adds missing folders to existing matters (never deletes).
- **Matter home**: Latest documents and Latest emails across all folders (newest first, folders ignored), team, key dates, notes, security summary, recent activity.
- **My Matters**: personal list of matter shortcuts; shareable lists (e.g. a partner's team list).
- **Follow a matter**: notification on new document, new version, profile change, new filed email (in-app + daily email digest).
- Bulk matter import (CSV) with dry-run validation report.
- Related matters (links: appeal of, same dispute, same client group).
- Matter notes (plain text, timestamped, author, searchable).

### M3. Document store
- **Document number**: every document gets a permanent firm-unique number; versions shown as `number.version` (e.g. `85423.4`). Copy number / copy internal link. Go-to by number from the search bar.
- Upload single / multi / folder / zip / drag-drop; resumable; virus scan; size + type policy. Mobile web upload (camera photo → OCR).
- Supported: PDF, DOCX, DOC, XLSX, XLS, PPTX, TXT, RTF, CSV, images (OCR), `.eml`, `.msg`.
- **Profile-on-upload** dialog: class required; other fields pre-filled from folder → matter → template defaults (Appendix B.2).
- Folder tree per matter; empty folders visually distinct from folders with content. Rename; soft delete → Trash; restore.
- Three placement actions with exact semantics:
  - **Move**: same document number, all versions, leaves the old location. Prompt "match security of destination" or "keep current security".
  - **Copy**: new document number, latest version only, independent from the original; banner "Open the new copy".
  - **Also file here** (shortcut): same document number and versions shown in a second folder; one edit updates every location.
  Folder shortcuts and matter shortcuts follow the same "pointer, not copy" rule.
- **Activities panel**: running and finished uploads, moves, copies, deletes with progress, retry failed, undo (where reversible), go to location.
- **My Documents** (everything I authored or last edited, up to 5,000), **Checked-out documents** (mine), **Emails filed by me**, **Recently filed emails**.
- Tree state (expanded folders, last location) restored after session timeout on the same browser; "reset layout" in user settings.
- Natural numeric sort (1, 2, 11, 22, 111) on names and numbers.
- **Related documents**: link a document to others (contract ↔ addenda, application ↔ order) shown on both sides.
- Saved filters (virtual folders built from profile values) per matter or personal.
- Duplicate detection (content hash) with "link instead of copy" prompt.
- **Details panel** with tabs: Profile · Versions · Preview · History · Related · Access.
- **Preview** in browser (PDF + Office via render-to-PDF): page navigation, thumbnails, find-in-document with highlight, select/copy text, full-screen, open two documents side by side.
- Download original, download as PDF, download folder/matter as zip. Downloaded filename carries document number and version.
- Favourites (documents, emails, folders, matters), Recents (documents, emails, folders, matters, clients — last 30 days), "Go to matter" quick switcher.
- List view and detail/grid view with resizable, choosable columns; side filters (date: today, yesterday, last 7 / 30 days, custom; file type; class; author/operator; matter fields).
- Mark as final (sets status Final and makes the version official).

### M4. Versioning & check-out
- Every check-in or upload onto an existing document creates a new version: number, **version comment** (required on check-in), author, timestamp, hash.
- Version comments are internal: never written into downloaded files, shares, or email attachments.
- Check-out (exclusive lock with owner, time, optional expiry; padlock shown everywhere the doc appears); check-in with new file; cancel check-out; admin force-unlock (audited); reminder notification for documents checked out more than N days.
- Version list; compare any two versions (text diff using existing `diff.py`); restore an older version as the new latest; mark **official**; lock a version against deletion.
- Conflict guard: checking in against a stale base version warns ("you started from v9, latest is v11").
- No co-authoring, no "overwrite current version" (every change is a new immutable version; simpler and safer).

### M5. Email capture & sync (no add-in required)
Four ways in, all ending in the same parsed-email pipeline.

**1. Upload** — drag `.eml` / `.msg` files (or a zip / `.mbox`) onto a matter folder.

**2. Matter filing address** — every matter (and optionally folder) gets an inbound address, e.g. `m-00042-0007@file.<firm-domain>`.
- Forward, CC or BCC to file. Works from any client and any phone.
- When a filed message is sent onward, the system adds a short matter tag to the subject (e.g. `[#00042-0007]`); replies carrying the tag that reach any synced mailbox file automatically (the "follows the thread" rule).
- Sender allowlist = firm users; unknown senders are quarantined for review, never auto-filed.

**3. Mailbox folder sync (Microsoft 365 via Graph, Gmail via Gmail API)**
- User connects their mailbox (OAuth, least-privilege scopes, admin consent for M365 tenant).
- User maps a mail folder (Outlook) or label (Gmail) to a matter/folder; anything they drag into it, on desktop or phone, is filed server-side within minutes.
- Optional per-user rules: "auto-file replies in threads already filed", "suggest matter from sender domain → client map". Suggestions appear in a web **Filing inbox** for one-click confirm. Rules are deterministic (thread id, domain map, matter tag); no ML in MVP.
- After filing, the message gets an Outlook category / Gmail label "Filed" so the user sees it in their mail client (our equivalent of a filed tick).
- Per-mapping options: **keep messages in mailbox after filing** (default on) or remove after filing · **file as private** (only me) ·
  **map sub-folders** (sub-folders created later need an explicit "map new sub-folders" action) · **copy messages already in the folder** at mapping time (default off).
- System folders (Inbox, Sent, Deleted, Drafts, Junk) cannot be mapped whole, so a whole mailbox is never filed by accident; Sent is allowed only in "tagged messages only" mode (route 4).
- Mapped folders get a visible suffix in the mail client (e.g. "· filed") so users know they are linked.
- Users can point mail-client rules at a mapped folder for automatic filing (documented in the quick-start).
- **Filing queue** page per user: pending, filed, failed (with reason) and retry / discard; an admin view across all users.
- **Access applied to filed email**, chosen per firm with per-filing override: *Inherit from matter folder* (default) · *Participants* (internal sender + To/CC users only) · *Only me*.

**4. Sent-mail filing** — the user maps their Sent folder with "file only messages carrying a matter tag", so tagged sent mail files itself.

**Pipeline (all four routes)**
- Parse headers (from, to, cc, bcc where available, date, subject, message-id, in-reply-to, references), body (HTML + text), attachments.
- **Dedupe**: one stored email per message-id + content hash across all recipients; additional filers are recorded as "also filed by".
- Store the original `.eml` as the record; attachments become child documents linked to the email, each searchable and OCR'd.
- **Multi-location filing**: the same email can be filed into several matters (one record, many locations).
- **Save attachment as new version** of an existing document; the version comment links back to the source email automatically; stale-version warning as in M4.
- Thread view per matter (group by references / conversation id), filter by participant, date, has-attachments.
- Email profile defaults: class = Email, matter from route, author = sender, doc date = sent date.
- Matter home shows "Latest emails"; colleagues see everything filed to the matter (subject to access).
- **Post-launch**: Outlook add-in (Send-and-file prompt, side panel, filing suggestions), Gmail Chrome extension, meeting-request filing.

### M6. Security & ethical walls
- Default access per matter: *Firm-wide view*, *Team only*, *Private (named users)*; documents inherit unless overridden.
- ACL levels: View, Download, Edit/Check-in, Manage (change security), Admin.
- Per-matter **view-only** switch (no download/print/export for listed groups); lightweight DLP for MVP.
- **Screens/walls**: deny rules per user or group on a matter or client; locked (not removable by matter owners); retroactive on existing documents; screened user cannot see matter, docs, emails, search hits, or Ask citations.
- Wall policy types: **Restricted / need-to-know** (only listed people and groups; inclusionary) · **Exclusion** (named conflicted people or lateral hires barred; exclusionary) ·
  **Opposing teams** (team A and team B on opposite sides of a deal or dispute cannot see each other's matters). Walls can sit at client, client group, matter, practice group or office level.
- Walls maintain themselves: adding someone to a matter team adds them to the matter's need-to-know list; removing them removes access; new lateral hires are checked against exclusion lists on activation.
- Time-limited access grants (e.g. 48 h urgent access) that expire automatically, and access granted only after approval by the responsible partner.
- **Two-person rule**: removing or weakening a wall needs a second approver (Records Manager or GC role).
- "Apply security to contents" with exceptions (skip private items, include non-inheriting subfolders, all versions vs. selected).
- Access requests with approver workflow (`access_requests`).
- Mass access change (select N documents/matters).
- Reports: who has/had access to matter X between dates; blocked-access attempts; wall change history.
- Unusual-activity alerts (rule-based): bulk downloads above threshold, access outside office hours, many failed access attempts → admin notification.
- Enforcement point is SQL (ACL epoch + `doc_acl_state`), never post-filter in Python or in the model.

### M7. Search & Ask the Firm (the only AI)
**Classic search**
- One search bar, scoped by context (in a matter → that matter; at home → firm) with a scope switch.
- Keyword / phrase full-text (Postgres `tsvector`, stemming) across document body, profile, version comments, emails and attachments; document-number lookup; filters on every profile field; date ranges; saved searches; snippets with hit highlight; sort by relevance / date / name.
- Search finds matters and clients too (by number, name, party).
- Query operators: `"exact phrase"`, `AND` / `OR` / `NOT`, wildcard `*` and `?`, proximity (`"term1 term2"~5`), field search (`author:`, `class:`, `matter:`), relative dates (`modified:-30..0`).
- Simple and advanced forms; advanced has "add another field" with a searchable field list; lookup fields match "starts with" or "contains".
- Search inside a saved-search folder or the current folder only ("current location" scope).
- Back to results after opening one; bookmarkable search URLs including filters.
- Result list export: print / CSV of chosen columns (e.g. a pleadings index for a matter) without needing an analytics licence.
- Workspace saved searches can be added to matter templates so every new matter gets them.
- In-preview search: exact phrase, match case, whole word, starts with, ends with, wildcards.

**Ask the Firm (find-only)**
- Input: natural-language question, optionally scoped to a matter (default: the matter you are in).
- Output: ranked list of **source passages with document number, version, page, matter, and open-at-page link**, plus a short
  extractive answer composed only from those passages. No drafting, no advice, no "write me a clause".
- **Matter facts card**: questions about the matter itself ("who is opposing counsel?", "next hearing date?", "who is the responsible partner?")
  are answered from the structured matter profile (Appendix B.1) and shown as profile fields, not generated text.
- "No relevant material found" is a first-class result.
- Guardrails: ACL filter in SQL before ranking · `MATTER_SCOPE=hard` · citation ids must come from retrieved set · every Ask logged to audit.
- Keep: `FUSION_POLICY=p55_repair_ce_protect`, MiniLM embeddings via the existing interface.
- Remove from MVP surface: chat sessions, tool-calling, follow-up agent, stored-answer editing, draft generation.
  (Ask history stays as a personal list of past queries.)

### M8. Records, retention, legal hold
- **Declare as record**: a document or email becomes immutable (no edit, new version, or delete except by Records Manager); shown with a record marker; logged.
- Document classes → retention schedule (years + trigger: matter closed date / doc date / manual).
- Matter close event stamps `closed_at`, computes `dispose_after` for each doc.
- **Legal hold** on matter, client, or document set: blocks delete, profile edits, and new versions per policy; overrides retention.
- Disposition queue: documents past retention → Records Manager reviews → approve/defer → certificate of destruction (audit row survives).
  Review can approve or reject at matter, folder or document level, with key profile fields shown beside each item.
- Retention digest: an email every 30 days (configurable) to Records Managers listing what has become eligible.
- Export retention: generated client-file exports auto-expire after N days.
- Physical records (barcodes, boxes, off-site storage) are out of scope.
- Closed matters become read-only (archival state); reopen is an audited action.
- Client file export: complete zip with folder structure, index CSV (profile + versions), email thread index.

### M9. Audit & compliance
- Append-only `audit_events`: view, preview, download, print/export, email-send, create, profile edit, new version, check-out/in, move, delete, restore,
  security change, wall applied/removed, share created/used, mail filed, login, failed access, Ask query.
- **History tab** on every document: chronological list of the above with user and timestamp.
- DB-level protection: no UPDATE/DELETE grant for app role; periodic hash-chain or signed manifest (`manifest_signer` exists).
- Audit viewer with filters (user, matter, doc, action, date) + CSV export; deletion report.
- Basic usage report for admins: active users, uploads, emails filed, searches, per practice area.
- Audit survives document purge.

### M10. External sharing
- Expiring secure link per document, version, or folder: optional passcode, lock to a specific version, allow/deny download, expiry date, revocable; every access logged.
- Guest users limited to explicitly shared items (can upload into a shared "inbound" folder if allowed).
- **Upload request**: send a link that lets an outside party upload up to N files (default 10) into a chosen matter folder before it expires; uploads are virus-scanned, profiled as "Received from client", and the requester is notified.
- Default link expiry set by admin (1–5 days presets, custom up to 90 days max).
- Subscribe to a shared folder: email when guests add, change or remove files.
- Admins see every guest user and every live link firm-wide and can revoke in bulk.
- Version comments and internal profile fields are never exposed to guests.

### M11. Migration & bulk ingest (critical for adoption)
- **Import wizard**: choose source (zip / folder upload / network-share connector / SharePoint / Google Drive / existing DMS export) → map folders to
  client/matter → map columns to profile fields (CSV) → dry run → commit in batches.
- Mail archive import: PST / mbox → matter mapping.
- Resumable, idempotent (content hash + source path key), per-file error report, retry failed.
- Preserve original dates, authors, and (when supplied) version chains.
- Throughput target: 100k docs/day per worker on pilot hardware; progress UI; pause/resume.
- Post-ingest: OCR queue, chunk + embed queue, search-ready status per document.

### M12. Admin & operations
- Lookups, templates, retention schedules, captions, limits, storage usage, queue health, failed-ingest dashboard, mail-sync health per mailbox.
- Outbound webhooks on events (document filed, matter opened/closed) + CSV exports for practice-management systems.
- Backups + restore drill, health checks, metrics (`app/observability`), rate limiting, security headers (exist).
- Ops hygiene: infrastructure as code, deploys only from CI, no interactive shell on production hosts, secrets in vault.

---

## 5. Data model (target; extends existing tables)

New or changed (names ours; check for collisions with the 40+ existing tables first):

| Table | Purpose |
|---|---|
| `clients` (extend) | client_no, status, contacts, conflict flag |
| `matters` (extend) | matter_no, type, practice_area, status, opened/closed dates, responsible_member, template_id, default_security, court/forum fields (Appendix B.1) |
| `matter_key_dates` | hearing / limitation / filing deadlines per matter |
| `matter_templates`, `matter_template_folders` | default folder tree + defaults |
| `lookup_tables`, `lookup_values` | doc classes, statuses, practice areas, courts, custom pick-lists |
| `profile_fields` | admin-defined fields (key, caption, type, required, lookup, scope doc/matter/folder) |
| `document_profile_values` | typed values per document (or JSONB `profile` + GIN index; decide in spike) |
| `document_numbers` | firm-unique sequence; number never reused |
| `folders` (extend `project_folders`) | matter folder tree, inherit flags |
| `document_locations` | doc ↔ folder many-to-many (multi-location) |
| `document_relations` | related documents (typed links) |
| `document_versions` (extend) | comment, is_official, is_locked, base_version |
| `emails`, `email_attachments`, `email_filings` | parsed message metadata, attachment links, who filed where (dedupe) |
| `mail_connections`, `mail_folder_mappings`, `mail_inbound_addresses`, `mail_filing_queue` | mailbox sync, filing addresses, suggestions inbox |
| `security_policies`, `security_policy_members` | reusable ACL templates, `is_wall`, `is_locked`, pending second approval |
| `retention_schedules`, `legal_holds`, `legal_hold_items`, `disposition_batches`, `record_declarations` | records management |
| `share_links`, `share_link_access` | external sharing |
| `saved_searches`, `favourites`, `my_matter_lists`, `follows`, `notifications` | user conveniences |
| `import_mappings` | reusable migration mappings |

Rules:
- Every migration additive and reversible; dated filenames like existing `20261008a_*.sql`.
- Permissions are columns/joins usable inside the retrieval SQL, not app-side checks.
- Audit table has no UPDATE/DELETE privilege for the app role.
- Mailbox OAuth tokens encrypted at rest, scoped per user, revocable by user and admin.

---

## 6. Architecture changes for the MVP branch

1. **Branch hygiene**: strip, don't delete from history. On `mvp/dms-core` remove assistant/editor/tabular/playbook routers from `app/api/main.py`
   and the frontend shell; leave code on source branches.
2. **Feature flags** (single `config.py` block): `FEATURE_ASSISTANT=false`, `FEATURE_AI_EDIT=false`, `FEATURE_TABULAR=false`,
   `FEATURE_WORD_EDITOR=false`, `FEATURE_ASK=true`, `FEATURE_MAIL_SYNC=true`. Routers register conditionally; CI asserts disabled routes are absent.
3. **Storage**: object store for blobs (local → S3/Azure Blob; see `AZURE_DEPLOYMENT_ROADMAP.md`), Postgres for metadata + vectors, Redis for queues.
   Deployment region selectable per firm (India region default for Indian firms).
4. **Workers**: ingest → AV → OCR → extract → chunk → embed → index as separate idempotent stages with status per document;
   mail workers: inbound SMTP receiver / Graph change-notification subscriber / Gmail push (Pub/Sub) → parse → dedupe → file.
5. **API**: versioned `/api/v1`, OpenAPI published, consistent error shape, pagination everywhere, idempotency keys on uploads.
6. **Frontend**: slim shell with Home (recents), Matters, Clients, Search, Ask, Filing inbox, Records, Admin, Audit. Reuse design tokens; drop assistant panes. Responsive down to phone width.
7. **Security hardening**: SSO, MFA, TLS everywhere, secrets in vault, CSP, upload sandbox/AV, encryption at rest (cloud KMS), per-tenant keys post-MVP (CMEK).

---

## 7. Phased delivery

Estimates assume 2 backend, 1 frontend, 0.5 QA/ops. Adjust to actual team.

| Phase | Weeks | Deliverables | Exit gate |
|---|---|---|---|
| **P0 Foundation** | 1 | Branch cut, feature flags, strip assistant/editor, green CI, ADRs for profile model + security model + mail capture, IP-origin record entry | `pytest` green, UI boots with reduced nav |
| **P1 Spine** | 2–3 | Clients/matters CRUD + lifecycle, templates, lookups, profile fields, captions, folder tree, users/groups/roles, service accounts, SSO | Create client → matter → folders from template via UI and API |
| **P2 Documents** | 3–4 | Document numbers, upload (single/bulk/zip/mobile), profile form + inheritance, details panel, preview, download, multi-location, related docs, trash, duplicates, favourites/recents/My Matters | 10k-doc pilot corpus loads; preview works for all supported types |
| **P3 Versions & locks** | 5 | Check-out/in, version list/compare/restore/official/lock, version comments, stale-base warning, checkout reminders | Concurrency tests pass (two users, one doc) |
| **P4 Security & walls** | 5–7 | Default access, ACLs, inheritance, apply-to-contents, locked walls, two-person removal, view-only, access requests, mass access change, access report, activity alerts | Permission matrix suite (≥300 cases) 0 leaks; walls retroactive |
| **P5 Search + Ask** | 6–8 | Profile + full-text search, saved searches, matter-scoped Ask (find-only UI), matter facts card, citation open-at-page, query audit | Retrieval gate §8 met; SQL-level ACL verified |
| **P6 Email capture** | 7–10 | `.eml/.msg/.mbox` upload, parse/dedupe pipeline, attachments, threads, filing addresses + subject tag, M365 Graph folder sync, Gmail label sync, Filing inbox, "Filed" marker, save attachment as version | Round-trip 500 sample emails, attachments intact; same email filed by 3 recipients stored once; phone-drag-to-folder files within 5 min |
| **P7 Audit & records** | 9–11 | History tab, audit viewer/export + append-only enforcement, declare record, retention schedules, legal holds, disposition queue, closed-matter read-only, client-file export, follow/notifications | Hold blocks delete in every code path; export reproduces matter |
| **P8 Migration & sharing** | 10–12 | Import wizard, CSV mappings, PST/mbox import, dry run, resumable batch runner, external share links | Pilot firm archive (target ≥100k docs) imported with <0.5% unresolved failures |
| **P9 Hardening & pilot** | 12–14 | Load test, pen-test fixes, backup/restore drill, runbooks, admin training, pilot onboarding | Launch checklist §9 complete |

Critical path: P1 → P2 → P4 → P5 → P8. P6 runs in parallel from week 7 with one backend dev (Graph/Gmail app registration and verification take calendar time; start the paperwork in P0).

---

## 8. Quality gates

### Retrieval / Ask (must pass before Ask is switched on for pilot)
- Run `python evals/retrieval_eval.py` against the frozen 445-question set; record in `docs/CHANGELOG.md` with numbers.
  (Note: that dataset targets an older corpus; also run `km_live_eval` for A/B on the current corpus.)
- Matter-scoped queries: no regression vs. current `p55_repair_ce_protect` baseline; report Recall@20 and MRR.
- 100% of returned citations map to a retrieved chunk id (automated check).
- "Unanswerable" probe set: ≥ 95% return "no relevant material" rather than a fabricated answer.
- Latency: p95 Ask < 6 s on pilot corpus; search p95 < 1.5 s. Verify through the running API, not only in-process.

### Security
- Permission matrix tests: user × matter × document × (wall, private, inherited, hold, view-only) with expected visibility in **search, Ask, preview, download, email threads, share links, audit**.
- Fuzz: a screened user's query must produce zero rows from any screened doc (check counts in SQL, not UI).
- Mail sync: a message filed by a user into a matter they cannot access is rejected and logged.
- Third-party pen test before external pilot.

### Data integrity
- Versions immutable (hash stored); restore creates new version.
- Ingest idempotency test: re-run same batch → 0 duplicates. Same for mail sync replay.
- Backup restore drill with checksum comparison.

### Compliance
- Audit log tamper test (app role cannot UPDATE/DELETE).
- Hold test across: delete, move, profile edit, new version, purge job, disposition job, declare/undeclare record.

---

## 9. Launch checklist

- [ ] Branch `mvp/dms-core` protected, CI required (tests, lint, route-absence check for disabled features)
- [ ] All P0–P9 exit gates met
- [ ] `DEPENDENCY_AUDIT.md` updated for every new package (esp. `.msg`/PST parser, OCR, AV, preview renderer, SMTP receiver: avoid GPL/AGPL/LGPL without approval)
- [ ] `IP_ORIGIN_RECORD.md` entry for this plan (see §11)
- [ ] Microsoft Entra app registration (Graph Mail.ReadWrite delegated, admin consent flow) and Google OAuth app verification for Gmail scopes completed
- [ ] Inbound mail domain (MX, SPF, DKIM, DMARC) for filing addresses
- [ ] Production infra from `AZURE_DEPLOYMENT_ROADMAP.md`: Postgres HA, blob storage, Redis, worker autoscale, backups, DR runbook, India region
- [ ] `AUTH_ENABLED=true`, SSO configured, API keys issued, default dev header trust off
- [ ] Admin guide, user quick-start (incl. "how to file email from your phone"), migration guide, incident runbook
- [ ] Pilot firm data-processing agreement, DPDP Act notice/consent and retention/jurisdiction settings signed off
- [ ] Support channel, SLA (target 99.5% for pilot), rollback plan, feature-flag kill switch for Ask and mail sync

---

## 10. Branch plan

```
git switch -c mvp/dms-core <stable integration commit>
# 1. commit: flags + remove assistant/editor/tabular wiring
# 2. commit per phase (P1..P9), each with tests + CHANGELOG entry
# 3. weekly: rebase onto main for shared fixes; never merge assistant code back in
```

Open decision: base commit. Candidates are `main` or the current `new_frontend_v2` (carries the newer UI shell but also
assistant-coupled code). Recommendation: cut from `main`, cherry-pick the UI shell pieces needed.

---

## 11. Clean-room note

iManage and NetDocuments are proprietary products, not AGPL, but the same discipline applies:
- We use their public documentation only to confirm *what problems a legal DMS must solve*.
- We choose our own schema, route names, UI copy, and visual design. No vendor prose, icons, screenshots, or terminology that is distinctive
  (e.g. "ndMail", "Workspace Security Manager", "Timeline", "luggage tag", "FIT code", "Echo", "CollabSpaces", "SetBuilder" as product names) in our UI or code.
  Appendix A uses vendor names only to say which feature each requirement answers.
- Mike (AGPLv3) remains product research only per `.cursor/rules/agpl-cleanroom.mdc`.
- Record this plan in `docs/legal/IP_ORIGIN_RECORD.md` before implementation begins.

---

## 12. References

- Repo: `NetDocs and iManage features guide.pdf` (Executive Knowledge Report, 7 pp.)
- Pasted report: "Enterprise Document Management Technical Architecture & Feature Analysis: iManage Work 10 vs. NetDocuments"
- iManage Work, containers and documents: https://docs.imanage.com/cloud/cc-help/en-US/Containers_and_Documents.html
- iManage Work, metadata: https://docs.imanage.com/cloud/cc-help/en-US/Metadata___.html
- iManage Work, container and document security: https://docs.imanage.com/cloud/cc-help/en-US/Container_and_Document_Security.html
- iManage Work Web, applying security to children: https://docs.imanage.com/cloud/work-web-help/en-US/Applying_workspace_or_folder_security_to_its_children.html
- iManage Work, declaring a record: https://docs.imanage.com/work-web-help/10.5.1/en-US/Declaring_a_record.html
- iManage Work, relating documents: https://docs.imanage.com/work-web-help/10.5.1/en-US/Relating_documents.html
- iManage Work, emailing documents and links: https://docs.imanage.com/work-web-help/10.5.0/en-US/Emailing_documents.html
- iManage Work, checked-out document notifications: https://docs.imanage.com/work-help/10.10.0/en/Notifications_for_checked_out_documents.html
- iManage Work, previewing documents: https://docs.imanage.com/work-web-help/10.5.0/en-US/Previewing_documents.html
- iManage Work interface foundations: https://registration.imanage.com/pages/imanage-work-interface-foundations
- iManage Work feature foundations: https://registration.imanage.com/pages/imanage-work-feature-foundations
- iManage Closing Folders: https://imanage.com/resources/resource-center/blog/how-imanage-closing-folders-helps-streamline-complex-deal-closing-processes/
- Work for Gmail (third-party extension): https://www.macroagilityinc.com/gmail2work/
- NetDocuments cabinet administration: https://support.netdocuments.com/s/article/205220270
- NetDocuments workspace overview: https://support.netdocuments.com/s/article/205233420
- NetDocuments version management: https://support.netdocuments.com/s/article/205217360
- NetDocuments ndOffice versions and attachments: https://support.netdocuments.com/s/article/360003006731
- NetDocuments ndClick tips: https://support.netdocuments.com/s/article/360004630312
- NetDocuments document/workspace options and user rights: https://support.netdocuments.com/s/article/204974474
- NetDocuments limits reference: https://support.netdocuments.com/s/article/205217370
- NetDocuments Workspace Security Manager: https://support.netdocuments.com/s/article/360055458011
- NetDocuments solutions brochure: https://pages.netdocuments.com/rs/549-CKV-717/images/netdocuments-solutions-brochure.pdf
- iManage Work, what's new (bulk actions, search, versions panel, security panel, tree persistence): https://docs.imanage.com/cloud/work-web-help/en-US/What's_new_in_iManage_Work.html
- iManage Work, creating workspaces: https://docs.imanage.com/cloud/work-web-help/en-US/Creating_workspaces.html
- iManage Desktop, filing an email: https://docs.imanage.com/work-help/10.10.0/en/Filing_an_email.html
- iManage Desktop, linking Outlook folders: https://docs.imanage.com/work-help/10.10.1/en/Linking_folders.html
- iManage Desktop, introduction to email management: https://docs.imanage.com/work-help/10.9.5/en/Introduction_to_Email_Management_(EM)_for_Outlook.html
- iManage tips for end users: https://docs.imanage.com/best-practices-and-knowledge-articles/Tips_for_iManage_Work_end-users.html
- iManage Security Policy Manager intro: https://docs.imanage.com/cloud/spm-admin-help/en-US/Introduction_to_iManage_Security_Policy_Manager.html
- iManage Share, upload request: https://docs.imanage.com/cloud/share-user-help/en-US/Configuring_the_Upload_Request.html
- iManage Records Manager: https://imanage.com/imanage-products/security-governance/records-manager/
- iManage Work 10 guide (third party): https://www.fabiantechtips.com/post/how-to-use-imanage-work-10-a-comprehensive-guide
- NetDocuments retention policies: https://support.netdocuments.com/s/article/205220220 · litigation hold: https://support.netdocuments.com/s/article/205220250
- NetDocuments folder packs: https://support.netdocuments.com/s/article/360050442352 · saved searches: https://support.netdocuments.com/s/article/205217900
- NetDocuments CollabSpaces: https://support.netdocuments.com/s/article/360034383652
- NetDocuments M365 Outlook administration: https://support.netdocuments.com/s/article/M365-Outlook-Administration
- NetDocuments efficiency features blog: https://www.netdocuments.com/blog/how-to-improve-efficiency-with-key-netdocuments-features-part-1-of-2-saving-time-and-clicks/
- NetDocuments 17.2 quick reference (third party): https://www.tsrconsult.com/wp-content/uploads/2017/08/NetDocuments-17.2-Quick-Reference-Guide.pdf
- NetDocuments user guide 2025 (third party): https://www.matrixsolutions.com.au/netdocuments-user-guide/
- ndMail review: https://finance.yahoo.com/news/review-deep-look-netdocuments-ndmail-133059448.html
- Copy vs move vs file in NetDocuments: https://www.optiable.com/whats-the-difference-between-copy-move-file-in-netdocuments/
- NetDocuments access levels (VESA): https://www.optiable.com/understanding-document-security-in-netdocuments-a-guide-for-users-vesa/
- Legal DMS buyer guidance: https://centerbase.com/blog/document-management-systems-for-law-firms/ ·
  https://skopx.com/resources/legal-document-management-software ·
  https://sendtocase.com/legal-document-management-software ·
  https://lexworkplace.com/features/document-management/ ·
  https://www.filevine.com/blog/must-have-features-for-any-legal-document-management-system/

---

## 13. Risks

| Risk | Mitigation |
|---|---|
| Scope creep back toward "AI features" | Feature flags + CI route-absence check; any AI beyond Ask needs a plan doc |
| Permission leaks via search/Ask/preview/email/share side channels | One SQL ACL predicate reused by every read path; matrix tests per path |
| Migration of messy archives dominates timeline | Build import wizard early (P8 can start at P2 with a CLI); dry-run reports; pilot with a real archive in week 6 |
| Office preview fidelity | Render-to-PDF pipeline with fallback to download; test corpus of ugly files |
| `.msg` / PST parsing library licensing | Audit before adoption; fall back to `.eml`/mbox-only at launch |
| Microsoft / Google OAuth verification delays (Gmail restricted scopes need a security assessment) | Start in P0; M365 first (most Indian firms use Outlook); filing address works with no OAuth at all |
| Firm IT refuses mailbox access | Filing address + upload cover the need; sync is opt-in per user |
| Retention rules vary by jurisdiction | Configurable schedules, no hard-coded defaults, human-approved disposition |
| Embedding re-index time on large archives | Search usable before embeddings finish (full-text first), Ask enabled per matter when indexed |
| Desktop Word/Outlook expectation | State clearly at launch; schedule add-in as first post-MVP epic |

---

## 14. Post-MVP backlog (explicitly deferred, in rough priority order)

1. Outlook add-in (send-and-file prompt, side panel, filing suggestions) and Gmail Chrome extension.
2. Court paper book / closing binder builder: pick documents → order → index page → continuous pagination → bookmarked PDF (high value for Indian litigation).
3. Desktop: Word/Excel/PowerPoint ribbon (save to DMS, document-number footer, open from DMS), offline cache with auto check-in, mapped drive / two-way sync.
4. PDF tools: merge, page stamps / Bates-style numbering, watermark, redaction with burned-in release copies.
5. External client portal / deal room with branding and guest uploads at scale.
6. Matter tasks and checklists; document comments / margin notes; Teams/Slack link-back.
7. Customer-managed encryption keys (BYOK); multi-region storage per matter.
8. Practice-management and billing integrations; Power-Automate-style connector; e-signature.
9. Conflict-check engine; AI profile enrichment; entity extraction from documents; MCP server for approved external agents.
10. No-code templates / intake forms; browser Word editing; real-time co-authoring; assistant, AI drafting/editing, tabular review.

---

## Appendix A — Complete feature catalog (iManage + NetDocuments, granular)

Every action, menu item, option, indicator, limit and rule found in: the feature-guide PDF, the pasted architecture
report, iManage Work Web / Desktop / Control Center / Share / Security Policy Manager help pages, NetDocuments support
articles, NetDocuments quick-reference guides, ndMail reviews, and third-party user guides (§12).

**Source key**: iM = iManage · ND = NetDocuments · PDF = feature-guide PDF · RPT = pasted report · WEB = vendor help / guides.
**Decision key**: **MVP** in launch scope · **Lite** simpler version in MVP (note says what) · **Post** deferred (§14) · **Out** not planned.
Vendor names appear only to say which need a row answers; our UI uses our own words (§11).

### A.1 Sign-in, account and personal settings

| ID | Feature | Detail (rules, options, limits) | Src | Decision | Ours |
|---|---|---|---|---|---|
| A1.01 | Sign in with username + password | local accounts for small firms and break-glass admin | ND WEB | MVP | M1 |
| A1.02 | Single sign-on | Entra ID / Google Workspace OIDC; just-in-time user creation off by default | both WEB | MVP | M1 |
| A1.03 | Multi-factor authentication | prompt at sign-in; TOTP app; SSO delegates MFA to IdP | ND WEB, iM WEB | MVP | M1 |
| A1.04 | Biometric unlock on mobile apps | Face/Touch ID | iM WEB | Out | no native app |
| A1.05 | Sign out; session timeout | idle timeout configurable by admin (default 8 h), absolute 24 h | both | MVP | M1 |
| A1.06 | Edit own profile | name, title, phone, photo; email read-only under SSO | ND WEB | MVP | M1 |
| A1.07 | Change password | local accounts only; strength rules | ND WEB | MVP | M1 |
| A1.08 | Profile picture or initials avatar | shown in lists, history, team panel | iM WEB | MVP | M1 |
| A1.09 | Language preference | UI language per user | iM WEB | Post | English only at launch |
| A1.10 | Default landing tab | Recent Matters / Favourites / Documents | iM WEB | MVP | user settings |
| A1.11 | Open-file behaviour per file type | title click vs double-click; preview / download / open in desktop app; separate for Office vs other types; "remember my choice"; "reset saved choices" | iM WEB | Lite | preview or download only (no desktop hand-off) |
| A1.12 | Reset cached layout | clears tree state, column choices | iM WEB | MVP | user settings |
| A1.13 | Default open/save locations for desktop add-in | per app incl. Outlook | ND WEB | Post | add-in |
| A1.14 | Delegate my home page to a colleague (view or edit) | e.g. secretary manages partner's home sections | ND WEB | Post | |
| A1.15 | Connected accounts | link mailbox (M365/Gmail) for mail sync; revoke | ND WEB | MVP | M5 |

### A.2 Home page and navigation

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A2.01 | Recent documents | any activity (opened, edited, added, previewed) in last 30 days; timespan and activity filter user-configurable | iM PDF RPT WEB | MVP | M3 |
| A2.02 | Recent documents count | ND shows 40 most recent | ND WEB | MVP | 30 days, paged |
| A2.03 | My Documents | everything I authored or last edited, beyond 30 days, up to 5,000 | iM WEB | MVP | M3 |
| A2.04 | Checked-out documents (mine) | list with check-out time and expiry | iM WEB | MVP | M4 |
| A2.05 | Recently filed emails | firm-visible emails filed recently that I can access | iM WEB | MVP | M5 |
| A2.06 | Emails filed by me | | iM WEB | MVP | M5 |
| A2.07 | Recent folders | | iM PDF RPT | MVP | M3 |
| A2.08 | Recent matters | iM: 20 max within 30 days; ND: up to 40 | both | MVP | 40 |
| A2.09 | Recent clients | | iM PDF RPT | MVP | |
| A2.10 | My Matters | personal matter shortcuts; auto-added when I create a matter; categories to group them (categories hold only matters or sub-categories) | iM WEB | MVP | M2 |
| A2.11 | Subscribe to another user's My Matters | show/hide subscriptions; reorder; add a shortcut into a subscribed user's list (if allowed) | iM WEB | MVP | M2 shared lists |
| A2.12 | Favourite matters | ND: up to 350 | ND WEB | MVP | no small limit |
| A2.13 | Favourite items | documents, emails, folders, searches; star icon; add from preview; drag onto favourites | both | MVP | M3 (drag Lite) |
| A2.14 | Favourite categories | folders inside favourites | iM WEB | MVP | |
| A2.15 | Customisable home sections | personal sections by time/topic, saved-search sections, link sections; drag to reorder; "save changes" | ND WEB | Lite | fixed sections + reorder; custom sections Post |
| A2.16 | "Go to matter" box | type number or name | ND WEB | MVP | quick switcher (Ctrl/Cmd-K) |
| A2.17 | Side navigation | Documents, Emails, Folders, Clients, Matters, Favourites; collapsible | iM WEB | MVP | |
| A2.18 | Tree view of Recent Matters / My Matters / Favourites | expand inline | iM WEB | MVP | |
| A2.19 | Tree state persistence | expanded folders and location restored after timeout; same browser only; renamed folder shows old name until refresh; deleted folder shows error then disappears | iM WEB | MVP | |
| A2.20 | Captions renamable | "Matters" ↔ "Projects"/"Workspaces"; "Clients" ↔ "Departments"/"Business units" | iM WEB | MVP | M1 captions |
| A2.21 | Breadcrumb / path display | click any level | iM WEB | MVP | |
| A2.22 | Back / forward / up | | iM WEB | MVP | browser back works everywhere (URL per view) |
| A2.23 | Show item location in tree | from actions menu | iM WEB | MVP | |
| A2.24 | Copy link to any item | internal deep link; opens only if viewer has access | iM WEB | MVP | |
| A2.25 | Notifications bell | background job status, alerts | iM WEB | MVP | Appendix I |
| A2.26 | Zoom and multi-monitor | Ctrl +/−, open views in new tabs | iM PDF RPT | MVP | |
| A2.27 | Keyboard navigation and screen reader support | Tab/Shift-Tab, arrows in lists, Enter/Space select, Esc closes dialogs; labelled controls | iM WEB | MVP | WCAG 2.1 AA target |

### A.3 Lists, views, columns and filters

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A3.01 | List view | fixed key properties | iM WEB | MVP | |
| A3.02 | Grid / detail view | choose columns from any profile field | both WEB | MVP | |
| A3.03 | Resize, reorder, add/remove columns | settings persist per user | iM WEB | MVP | |
| A3.04 | Summary vs list view of workspace | | ND WEB | MVP | matter home vs folder list |
| A3.05 | Sort by any column | numeric-aware sort | iM WEB | MVP | |
| A3.06 | Group by column | e.g. by class | ND WEB | Post | |
| A3.07 | Filter: date | Today, Yesterday, Last 7 days, Last 30 days, Last 6 months, date range (keyboard entry + picker), All | iM WEB | MVP | |
| A3.08 | Filter: file type | multi-select; grouped (document, spreadsheet, presentation, PDF, email, image) | iM WEB | MVP | |
| A3.09 | Filter: class, author, operator, matter fields | | iM RPT | MVP | |
| A3.10 | Filter counts | number of active filters per category; filters narrow each other | iM WEB | MVP | |
| A3.11 | Pagination | prev/next and jump to page | iM WEB | MVP | |
| A3.12 | Multi-select with toolbar | bulk actions on selection | iM WEB | MVP | |
| A3.13 | Right-click / actions menu on every item | consistent action list (see A.6) | both | MVP | |
| A3.14 | Customise the actions menu | reorder/hide items | ND WEB | Post | |
| A3.15 | Print list | print current list / search results | ND WEB | MVP | print-friendly view + CSV |

### A.4 Libraries, cabinets and containers

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A4.01 | Library / cabinet | top-level store created by admin; users get access per cabinet | both WEB | Lite | one library per firm; multi-library Post |
| A4.02 | Preferred library per user | holds personal settings | iM WEB | Out | single library |
| A4.03 | Workspace (matter) | root container; holds only folders and tabs; cannot be nested | iM WEB | MVP | M2 |
| A4.04 | Tab | top-level grouping inside a matter; holds only folders; can stop inheriting security | iM WEB | Lite | top-level folders act as tabs |
| A4.05 | Folder | holds folders, documents, emails; has a doctype (Documents / Emails / custom) | iM WEB | MVP | folder "kind" drives default class |
| A4.06 | Folder limits | up to 10,000 folders per workspace | iM WEB | MVP | no hard limit; test at 10k |
| A4.07 | Search folder (saved search shown as folder) | can contain other search folders | iM WEB | MVP | saved filters |
| A4.08 | Folder shortcut | pointer to a folder elsewhere | iM WEB | MVP | |
| A4.09 | Document reference (shortcut) | pointer to a document in another folder | iM WEB | MVP | "Also file here" |
| A4.10 | Share folder (external) | folder synced to the sharing portal | iM WEB | Lite | share link on folder |
| A4.11 | Filters (virtual folders from profile values) | auto-generated from templates | ND WEB | MVP | |
| A4.12 | Folder packs | add a predefined set of folders with security and profile values to an existing matter | ND WEB | MVP | "add folder set" from template |
| A4.13 | Force filing in a folder (no loose documents at matter root) | cabinet setting | ND WEB | MVP | firm setting, default on |
| A4.14 | Empty-folder vs non-empty icons | | iM PDF WEB | MVP | Appendix E |
| A4.15 | Folder not inheriting security icon | | iM WEB | MVP | Appendix E |
| A4.16 | Folder with external access icon | | iM WEB | MVP | Appendix E |

### A.5 Clients and matters

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A5.01 | Create client | number (auto or manual), name, group, contacts, status | both | MVP | J-01 |
| A5.02 | Client group (parent entity) | rolls up several clients | iM WEB | MVP | |
| A5.03 | Create matter | dialog: template (last used pre-selected, alphabetical list, filter box), name, description, library, required properties, security section with template defaults and user/group search | iM WEB | MVP | J-02 |
| A5.04 | Matter from lookup table | matter list fed from practice-management system | ND WEB | Lite | CSV / API import |
| A5.05 | Matter actions | open, add/remove favourites, add/remove My Matters, copy link, properties, share/unshare, delete | iM WEB | MVP | delete only if empty |
| A5.06 | Workspace templates | admin-built; folder kinds: created-with-matter, optional (add later), required (auto-created under a parent) | iM WEB | MVP | |
| A5.07 | Enforce templates ("flexible folders" off) | users cannot add ad-hoc folders where template forbids | iM WEB | MVP | firm setting |
| A5.08 | Who may create folders | root: full matter access; inside folders: read/write on parent; public folders need "create public folders" right; cannot add folders inside template-locked folders | iM WEB | MVP | Appendix G |
| A5.09 | Template folders inherit parent security | can be renamed if template allows; can be re-added if deleted | iM WEB | MVP | |
| A5.10 | Saved searches in templates | appear on every new matter | ND WEB | MVP | |
| A5.11 | Re-apply template | adds missing folders only | ND WEB | MVP | |
| A5.12 | Matter profile fields | see Appendix B.1 | both | MVP | |
| A5.13 | Matter lifecycle | pending, open, on hold, closed, archived | both | MVP | |
| A5.14 | Follow matter | notify on new doc, new version, profile change | iM ND WEB | MVP | |
| A5.15 | Matter tasks / checklists | | ND PDF | Post | |
| A5.16 | Matter notes | | baseline | MVP | |
| A5.17 | Related matters | | baseline | MVP | |
| A5.18 | Matter number search ("go to") | | ND WEB | MVP | |
| A5.19 | Matter team panel | members with roles; avatars; disabled / external / wall-restricted user markers | iM WEB | MVP | |

### A.6 Document actions (the actions menu, item by item)

| ID | Action | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A6.01 | Open | preview in browser; multi-open up to 50 with warning above 20 | both | MVP | preview / download |
| A6.02 | Open in desktop app (edit) | checks out automatically | both | Post | M4 manual check-out + upload |
| A6.03 | Preview | from click, actions menu, or details panel | iM WEB | MVP | |
| A6.04 | Download | single or multiple (zip) | both | MVP | |
| A6.05 | Download as PDF | Office → PDF render | iM WEB | MVP | |
| A6.06 | Save as PDF as new document or new version | | iM WEB | Lite | "Create PDF version" as new document |
| A6.07 | Upload new version | | both | MVP | |
| A6.08 | Check out / check in / cancel | | both | MVP | |
| A6.09 | Unlock | owner with unlock right, or admin | both WEB | MVP | |
| A6.10 | Versions | list, compare, restore, official, lock | both | MVP | |
| A6.11 | Lock version | protect official version from edits | ND WEB | MVP | |
| A6.12 | Properties / edit profile | | both | MVP | |
| A6.13 | Rename | | ND WEB | MVP | |
| A6.14 | Move | same ID, all versions; match-destination-security prompt | both | MVP | |
| A6.15 | Copy | new ID, current version only; "open after creating" option | both | MVP | |
| A6.16 | File in another folder (shortcut) | same ID, one document | ND WEB | MVP | |
| A6.17 | Unfile from a folder | removes one location, keeps document | ND WEB | MVP | |
| A6.18 | Relate / link documents | one-to-many and many-to-one; link stored in profile | both | MVP | |
| A6.19 | Copy link | internal link | both | MVP | |
| A6.20 | Email link (internal recipients with access) | | ND WEB | MVP | mailto with link |
| A6.21 | Email copy (attachment) | | ND WEB | Lite | download then attach; server send Post |
| A6.22 | Deliver secure link (external) | password, version lock, download allow, expiry | ND WEB | MVP | M10 |
| A6.23 | Share with users (change access) | needs Share right | both | MVP | |
| A6.24 | Security panel | default security, user/group list, access levels, inherit toggle | iM WEB | MVP | |
| A6.25 | Follow document | email when someone else changes it | ND WEB | MVP | |
| A6.26 | Approve | marks "Approved" with user and time; any later change clears it; logged | ND WEB | MVP | small and useful |
| A6.27 | Mark as final | | iM PDF | MVP | |
| A6.28 | Declare / undeclare record | single or bulk; from folders, search results, recents, filed emails | iM WEB | MVP | |
| A6.29 | History / timeline | | both | MVP | |
| A6.30 | Add to favourites | | both | MVP | |
| A6.31 | Show location in tree | | iM WEB | MVP | |
| A6.32 | Print | | both | Lite | print from preview, logged |
| A6.33 | Delete | to trash; needs Administer/Full right | both | MVP | |
| A6.34 | Delete a single version | needs Administer | ND WEB | MVP | Records Manager only; blocked by hold/record |
| A6.35 | Export (selected / folder) | zip, chosen format | ND WEB | MVP | |
| A6.36 | Compare with another version | | both | MVP | |
| A6.37 | Add tags | free tags | ND WEB | MVP | tags field |
| A6.38 | Add notes / comments without changing the file | | ND WEB | Post | MVP: version comment + matter notes |
| A6.39 | Annotate / highlight in viewer | | ND PDF | Post | |

### A.7 Creating, uploading and saving

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A7.01 | Upload files | browse; up to 150 files per batch (ND); progress per file; confirmation | ND WEB | MVP | no small cap; resumable |
| A7.02 | Drag-and-drop onto folder | | both | MVP | |
| A7.03 | Upload folder / zip keeping structure | | baseline | MVP | |
| A7.04 | Upload from connected cloud storage | Drive, OneDrive | ND WEB | Lite | via import wizard (M11) |
| A7.05 | Create blank document from type | "Add > New": name, format, location | ND WEB | Post | |
| A7.06 | File size limits | iM up to 64 GB; ND under 1 GB per document | both WEB | MVP | 2 GB default, admin-set |
| A7.07 | Profile while uploading | metadata, tags, location | ND WEB | MVP | |
| A7.08 | Profile templates (saved sets of field values) | "save as template", "clear profile", default template per cabinet | ND WEB | MVP | |
| A7.09 | Security warning on save | if security, access list or client/matter differ from target folder | iM WEB | MVP | |
| A7.10 | Background OCR | 24/7; scans and photos become searchable; preserve modified user/date | ND PDF WEB | MVP | |
| A7.11 | Duplicate detection | | baseline | MVP | |
| A7.12 | Virus scan | | baseline | MVP | |
| A7.13 | Activities dialog | upload/copy/move/reference/delete progress; go to location; properties; undo; retry; expand/collapse; clear | iM WEB | MVP | |
| A7.14 | Bulk import tool | large migrations from file shares | iM WEB | MVP | M11 |
| A7.15 | Import error help | e.g. missing internal-users group | ND WEB | MVP | wizard pre-checks |

### A.8 Profile fields and properties panel

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A8.01 | Properties always show all fields | editable ones show an edit icon on hover/focus | iM WEB | MVP | |
| A8.02 | Inline editing rules | text saves on blur/Tab; Esc reverts; dates by keyboard or picker; yes/no fields have a "not set" state | iM WEB | MVP | |
| A8.03 | Lookup fields | relevance-ordered; first result auto-selected; Enter picks; arrows browse; "starts with" or "contains" (contains default for custom fields) | iM WEB | MVP | |
| A8.04 | Profile attributes on documents, folders and matters | folders can carry a profile that documents inherit | ND WEB | MVP | |
| A8.05 | Custom fields (custom1…N) with captions | | iM WEB | MVP | |
| A8.06 | Required fields enforced on save / filing | "on and force" for email filing | ND WEB | MVP | |
| A8.07 | Document ID format | library!number.version | iM WEB | MVP | `number.version` |
| A8.08 | Modified by / modified date shown | | ND WEB | MVP | |
| A8.09 | Mass profile edit | | ND WEB | MVP | |
| A8.10 | AI metadata extraction | | iM RPT | Post | |
| A8.11 | Entity findings in viewer | people, places, companies | ND PDF RPT | Post | |

### A.9 Preview and viewer

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A9.01 | View without download, check-out or native app | | iM WEB | MVP | |
| A9.02 | Full-screen | | iM PDF | MVP | |
| A9.03 | Find in document | exact phrase, match case, whole word, begins with, ends with, `*` and `?` wildcards, proximity with `~` | iM WEB | Lite | phrase, case, whole word; wildcards/proximity Post |
| A9.04 | Highlight hits | | iM PDF RPT | MVP | |
| A9.05 | Select and copy text | | iM PDF RPT | MVP | logged as "copied text" (no content) |
| A9.06 | Multi-page scroll, page jump | | iM RPT | MVP | |
| A9.07 | Timeline from preview toolbar | | iM WEB | MVP | History tab |
| A9.08 | Preview failure / long-wait guidance | tells the user to download instead | iM WEB | MVP | |
| A9.09 | Email preview with attachments | | iM WEB | MVP | |
| A9.10 | Margin notes and markup | | ND PDF RPT | Post | |
| A9.11 | Side-by-side two documents | | iM PDF | MVP | |

### A.10 Versions and journaling

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A10.01 | Version numbers .1, .2 … | | both | MVP | |
| A10.02 | New version from a chosen older version | highlight the base version, add description | ND WEB | MVP | "start new version from v3" |
| A10.03 | Version comment | required on new version; inline edit later; show/hide one or all comments | iM WEB | MVP | |
| A10.04 | Compact versions list | for long histories | iM WEB | MVP | |
| A10.05 | Multi-select versions | e.g. change permissions on several versions | iM WEB | MVP | |
| A10.06 | Version-level access restriction | hide a draft version from some users | ND WEB | Post | |
| A10.07 | Official version | | ND WEB | MVP | |
| A10.08 | Promote older version to latest | | iM PDF | MVP | |
| A10.09 | Compare two versions | | both | MVP | |
| A10.10 | Save & sync (overwrite current) | | iM PDF RPT | Out | |
| A10.11 | Journaling (edit snapshots for recovery, auto, non-configurable; deleted when doc purged) | | iM WEB | Out | no desktop editing; every upload is a version |
| A10.12 | Up to 32k versions | | ND WEB | MVP | |

### A.11 Check-out, locks and local copies

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A11.01 | Check-out locks for others | padlock icon | both | MVP | |
| A11.02 | Check-out comment and due date | | baseline | MVP | |
| A11.03 | "Unavailable" lock state | local copy lost; after unlock the last server version is current | iM WEB | Lite | admin force-unlock covers it |
| A11.04 | Unlock rights | owner with unlock privilege, or admin | iM WEB | MVP | |
| A11.05 | Checked-out reminders | | iM WEB | MVP | |
| A11.06 | Echo / shadow local copy | enabled per class; often forbidden by firms | both WEB | Out | |
| A11.07 | Offline editing with auto sync | | ND PDF | Post | |

### A.12 Trash, delete, records, retention, hold

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A12.01 | Personal trash | in user menu | iM PDF WEB | MVP | |
| A12.02 | Restore from trash | user or admin | iM PDF | MVP | |
| A12.03 | Permanent delete (purge) | admin only; removes journal copies | iM WEB | MVP | Records Manager; audit kept |
| A12.04 | Bulk delete | empty folders, docs + empty folders, folders with only empty sub-folders | iM WEB | MVP | non-empty folder delete blocked |
| A12.05 | Declare record | no edit/delete except admin; record icon; history entry | iM WEB | MVP | |
| A12.06 | Retention policies | by matter type, closing date, other criteria; two kinds: document retention and export retention | ND WEB | MVP | |
| A12.07 | Retention digest email | every 60 days to admins | ND WEB | MVP | every 30 days, configurable |
| A12.08 | Litigation hold | on workspaces; blocks profile edits, edits to existing versions, delete | ND WEB | MVP | matter, client or selection |
| A12.09 | Disposition review | at matter, workspace, folder or document level; reviewer sees key metadata; approve or reject | iM WEB | MVP | |
| A12.10 | Physical records, barcodes, boxes, off-site warehouse | | iM WEB | Out | |
| A12.11 | Secure deletion | | ND WEB | MVP | object store delete + key destruction Post |

### A.13 Email — capture, filing, display

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A13.01 | Browse and File dialog | from ribbon, right-click, or task pane | iM WEB | Lite | web "File to matter" picker in Filing inbox |
| A13.02 | Suggested locations / recent locations lists | | iM WEB | MVP | Filing inbox suggestions |
| A13.03 | Picker search | type matter name, Enter; folder search icon; restrict to one library or all; sort by relevance, name or client-matter | iM WEB | MVP | |
| A13.04 | Picker left pane | recent folders, matters, recent clients, favourites, recent matters, My Matters | iM WEB | MVP | |
| A13.05 | Picker right pane | contents, resizable divider, back/forward/up, path links, pagination, date filter, details tabs (properties, preview, versions, attachments) | iM WEB | MVP | |
| A13.06 | Auto-search after 1 s pause | | iM WEB | MVP | debounce 300 ms |
| A13.07 | Picker column chooser | persists locally | iM WEB | Post | |
| A13.08 | File to multiple locations checkbox | add locations then file once | iM WEB | MVP | |
| A13.09 | Filed icon on the message | | iM WEB, ND | MVP | "Filed" category / label |
| A13.10 | Filing details pane / columns | where and by whom filed | iM WEB | MVP | shown in our web UI |
| A13.11 | Global filing indicator for every recipient | colleagues see it was filed; avoids duplicates | ND WEB | MVP | sync applies "Filed" to every connected recipient's copy |
| A13.12 | One stored copy per email | extra locations add references, not copies | ND WEB | MVP | |
| A13.13 | Original filer keeps edit/rename rights | | ND WEB | MVP | |
| A13.14 | Predictions with strength bars | uses from/to/cc/subject, some body text, attachment names, recent filings; firm-wide history | ND WEB | Lite | rules only; confidence shown as High/Medium |
| A13.15 | One-click filing; auto-file on next selection | | ND WEB | Post | add-in |
| A13.16 | Prompt to file outgoing mail | | ND iM | Post | add-in; route 4 instead |
| A13.17 | Move filed items to an Outlook folder automatically | | ND WEB | Post | |
| A13.18 | Background filing (keep working) | | ND WEB | MVP | server-side by design |
| A13.19 | Linked / mapped mail folders | right-click "link"; pick target; options keep in Outlook (default), file as private, map sub-folders; cannot link default folders; later sub-folders not auto-mapped; "File now"; linked suffix and icon; Exchange limit beyond 100 linked folders | iM ND WEB | MVP | M5 route 3 |
| A13.20 | Copy existing messages when mapping | optional | ND WEB | MVP | default off |
| A13.21 | Mapped-message category colour | | ND WEB | MVP | "Filed" category |
| A13.22 | Filing queue: current and failed; clear queue | | ND WEB | MVP | |
| A13.23 | Participants access for filed mail | internal sender + To/CC get access | ND WEB | MVP | |
| A13.24 | Me-only access for filed mail | | ND WEB | MVP | |
| A13.25 | Choose where filing is allowed | workspaces, filters, folders | ND WEB | MVP | folders of kind Email or any |
| A13.26 | Mobile filing by moving mail into mapped folder (swipe → Move) | | iM WEB | MVP | |
| A13.27 | Outlook rules into linked folders | | iM WEB | MVP | documented |
| A13.28 | Send and file with subject tag; replies inherit | | iM PDF RPT | MVP | matter tag |
| A13.29 | Offline filing via send-and-file | | iM WEB | Post | |
| A13.30 | File meeting requests and tasks | | iM WEB | Post | |
| A13.31 | File from search folders | | iM WEB | Post | |
| A13.32 | Auto actions after filing: print, mark private, delete | | iM WEB | Lite | mark private; delete-after-filing option |
| A13.33 | Re-file to a different location | | iM WEB | MVP | move email |
| A13.34 | Save attachments: one, all, new document or new version | new version keeps location; all to one location in one action | iM WEB | MVP | |
| A13.35 | Insert DMS document into a new email as attachment or link | | iM WEB | Post | add-in |
| A13.36 | Preview DMS link attachments in reading pane | | iM WEB | Post | |
| A13.37 | Full DMS panel inside Outlook (dock/undock, resize, multi-monitor) | | iM WEB | Post | |
| A13.38 | Search the DMS from Outlook | | both | Post | |
| A13.39 | Copy emails between locations | drag to tree or actions menu | iM WEB | MVP | |
| A13.40 | Open email in mail app or Gmail | "open in Gmail" admin setting | iM WEB | Lite | download `.eml` |
| A13.41 | Old EMS folders with hourly archive and "archive now" | | ND WEB | Out | replaced by sync |
| A13.42 | Required profile fields when filing ("on and force") | | ND WEB | MVP | |

### A.14 Desktop and Office integration

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A14.01 | Office add-ins (Word, Excel, PowerPoint, Visio, Outlook) | open, save, profile, version, search inside the app | both PDF | Post | |
| A14.02 | Adobe add-in | | ND PDF | Post | |
| A14.03 | Ribbon: save as PDF, versions, compare, footer, send link, version recovery | | iM PDF WEB | Post | |
| A14.04 | Footer stamp (doc number, version, library) | | iM PDF | Post | number in filename at launch |
| A14.05 | Mapped virtual drive | | iM PDF RPT | Post | |
| A14.06 | Two-way folder sync | | ND PDF RPT | Post | |
| A14.07 | Browser ↔ desktop hand-off helper | | ND PDF WEB | Post | |
| A14.08 | Mobile apps (iOS/Android) with offline and annotation | | iM WEB | Post | responsive web |
| A14.09 | Teams integration | | both | Post | |

### A.15 Security, access and walls

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A15.01 | Access levels View / Edit / Share / Administer / No access | View: open, read, see versions and access list, download; Edit: change content, versions, profile, rename, file/unfile in folders, add saved search; Share: add users up to own level; Administer: delete docs/versions/folders, change and remove access entries, rename folder; No access: invisible | ND WEB | MVP | our levels: View, Download, Edit, Manage, Admin + Deny (Appendix G) |
| A15.02 | Default security public / view / private | | iM WEB | MVP | |
| A15.03 | Inherit from parent toggle | per folder/tab | iM WEB | MVP | |
| A15.04 | Apply security to children | single or many folders; status shown in notifications | iM WEB | MVP | |
| A15.05 | Align selected items with parent security | bulk | iM WEB | MVP | |
| A15.06 | Match-destination security on move | | iM WEB | MVP | |
| A15.07 | Cabinet default access | | ND WEB | MVP | firm default |
| A15.08 | Profile-based security | access driven by a profile value (e.g. client) | ND WEB | MVP | matter-level policy |
| A15.09 | Walls: restricted, opposing, conflicted-user exclusion | at client, client group, matter, case, department, location | iM WEB | MVP | |
| A15.10 | Self-maintaining walls | follow team changes and new hires | iM WEB | MVP | |
| A15.11 | Self-service access with time limit | | iM WEB | MVP | |
| A15.12 | Access after approval by team member / responsible attorney | | iM WEB | MVP | |
| A15.13 | Delegated wall admin to matter owners | | iM WEB | Lite | owners request, Records Manager approves |
| A15.14 | Wall dashboards, timelines, reports; feed to SIEM | | iM WEB | Lite | reports + CSV; SIEM export Post |
| A15.15 | Sync users/groups from directory | | iM WEB | MVP | SCIM or IdP group sync |
| A15.16 | User markers: disabled, external, wall-restricted | | iM WEB | MVP | |
| A15.17 | DLP rules (block download/print) | | ND PDF RPT | Lite | view-only switch |
| A15.18 | Insider-threat analytics | | iM PDF | Lite | rule alerts |
| A15.19 | Customer-managed keys, BYOK | | both | Post | |
| A15.20 | Geo storage | | ND | Lite | region per firm |

### A.16 External collaboration

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A16.01 | Secure link with password, version lock, download allow/deny, expiry | | ND WEB | MVP | |
| A16.02 | Collaboration link for several documents | expired-share icon; creator/editor auto-added; automated guest emails manageable | iM WEB | MVP | |
| A16.03 | Upload request | named or external users; up to 10 files; until expiry; "Upload request from <firm>" email; default recipient for notifications | iM WEB | MVP | |
| A16.04 | Link expiry presets | 1–5 days or custom, max 90 days | iM WEB | MVP | |
| A16.05 | Watermark on shared documents | | iM WEB | Post | |
| A16.06 | Subscribe to shared folder changes | add / change / remove | iM WEB | MVP | |
| A16.07 | External groups created by internal users | | ND WEB | Lite | admins create guests; owners invite |
| A16.08 | New content in shared space auto-shared | | ND WEB | MVP | folder shares |
| A16.09 | Upload alerts only at share root (ND limitation) | | ND WEB | MVP | we alert at every level |
| A16.10 | Mixed permissions inside one shared space | | ND WEB | Post | |
| A16.11 | Admin visibility of all external users | | ND WEB | MVP | |
| A16.12 | Branded portal / deal room | | both | Post | |
| A16.13 | Client drop zone (simple inbound upload page) | | iM WEB | MVP | upload request covers it |

### A.17 Search

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A17.01 | Search bar with type selector | documents, emails, folders, matters, clients | iM WEB | MVP | |
| A17.02 | Quick search across content and profile | ND: whole cabinet | ND WEB | MVP | |
| A17.03 | Advanced search on by default (toggle) | add-another-field with searchable list | iM WEB | MVP | |
| A17.04 | Boolean, wildcard, phrase | | both WEB | MVP | |
| A17.05 | Date range and relative dates (−30 to +0) | | ND WEB | MVP | |
| A17.06 | File type / extension search | | ND WEB | MVP | |
| A17.07 | Email tab in advanced search; filter by person (to/from) | | ND WEB | MVP | |
| A17.08 | Search group members ("find member") | | iM WEB | MVP | admin |
| A17.09 | Current-location scope (folder / search folder) | simple form only | iM WEB | MVP | |
| A17.10 | Back arrow to results | | iM WEB | MVP | |
| A17.11 | Bookmark search incl. filters | | iM WEB | MVP | |
| A17.12 | Numeric titles searchable | | iM WEB | MVP | |
| A17.13 | Saved searches, personal and shared library | | ND WEB | MVP | |
| A17.14 | Search result reports (columns, print, delivery) | | ND WEB | MVP | CSV/print |
| A17.15 | Stemming | | iM RPT | MVP | |
| A17.16 | Personalised ranking | | iM RPT WEB | Post | |
| A17.17 | Federated search across other systems | | ND PDF RPT | Post | |

### A.18 History, audit and analytics

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A18.01 | Document timeline | who, what, tool used, when; since first filed | iM WEB | MVP | |
| A18.02 | Timeline defaults | last 3 months default; "date range"; "all"; list view; 4+ actions within an hour grouped | iM WEB | MVP | |
| A18.03 | Timeline links to copies made | | iM WEB | MVP | |
| A18.04 | Folder history | edits, access changes, profile changes, renames, deletions | ND WEB | MVP | |
| A18.05 | Download earlier edit from timeline | | iM WEB | Out | (journaling) |
| A18.06 | Usage analytics | adoption, collaboration, lifecycle | ND PDF | Lite | admin report |

### A.19 Admin console

| ID | Feature | Detail | Src | Decision | Ours |
|---|---|---|---|---|---|
| A19.01 | Users: create, disable, delete, re-add | history kept | ND WEB | MVP | disable only; delete = anonymise Post |
| A19.02 | Groups | internal and external | both | MVP | |
| A19.03 | Roles and privileges | unlock, create public folders, create public searches, delete, import, trash purge… | iM WEB | MVP | Appendix G |
| A19.04 | Captions | | iM WEB | MVP | |
| A19.05 | Classes / subclasses (+ per-class settings) | | iM WEB | MVP | |
| A19.06 | Custom doctypes for folders | | iM WEB | MVP | folder kinds |
| A19.07 | Templates | | both | MVP | |
| A19.08 | Lookup tables | | ND WEB | MVP | |
| A19.09 | Cabinet / firm settings | force filing in folder, email filing targets, filed-email access options, default access, guest-share defaults | ND WEB | MVP | Appendix H |
| A19.10 | Save-dialog security alert on/off | | iM WEB | MVP | |
| A19.11 | Multi-version permission editing on/off | | iM WEB | MVP | |
| A19.12 | Open-in-Gmail on/off | | iM WEB | Lite | |
| A19.13 | Web client settings | | iM WEB | MVP | |
| A19.14 | Service account for automation | | ND RPT | MVP | |
| A19.15 | Service status subscription | | ND WEB | MVP | status page |

### A.20 Automation, AI and other suites (logged for completeness)

| ID | Feature | Src | Decision |
|---|---|---|---|
| A20.01 | No-code app builder and every sub-feature (app types, page/logic/navigation blocks, variables, expressions, developer mode, snapshots, sandbox, Word/PDF/email templates, `<< >>` conversion, conditional sections, triggers) | ND PDF RPT | Out |
| A20.02 | Outbound webhooks | ND RPT | Lite (event webhooks) |
| A20.03 | Power Automate connector | iM RPT WEB | Post |
| A20.04 | Data tables, background apps | ND | Out |
| A20.05 | Natural-language Q&A with citations | iM PDF RPT | MVP (Ask the Firm, find-only) |
| A20.06 | AI review projects, comparison tables, risk ranking, drafting | iM PDF | Out |
| A20.07 | Knowledge graph layer | iM PDF | Out |
| A20.08 | MCP server for outside AI agents | iM PDF RPT | Post |
| A20.09 | Smart suggestions (attachments, filing, sync, timelines), key-info extraction | iM WEB | Post |
| A20.10 | Chat threads on documents, Teams link | ND PDF RPT | Post |
| A20.11 | Tasks, trackers, checklists | both | Post |
| A20.12 | Closing binders / set builder, signature-page detection, closing books | both | Post (paper books first) |
| A20.13 | Zero-trust infrastructure items (micro-segmentation, signed images, no shell, egress block, peer review of policy edits) | iM PDF RPT | Lite (see A15, M12) |
| A20.14 | 3-layer key hierarchy, quantum RNG, FIPS 140-2 L3, near-site encryption | ND PDF RPT | Post / Out |
| A20.15 | Uptime 99.98% | iM PDF | Lite (99.5% pilot) |

---

## Appendix B — Profile field lists

### B.1 Matter profile (everything the firm needs to store about a matter)

| Group | Fields |
|---|---|
| Identity | client (link), matter number (auto), matter name, short description, internal code / billing code, engagement letter reference |
| Classification | practice area, matter type (litigation, arbitration, advisory, transaction, regulatory, IP, employment, other), sub-type, industry, confidentiality level, tags |
| People | responsible partner, originating partner, team members with role (partner, associate, paralegal, secretary), office, external co-counsel |
| Parties | client role (claimant/respondent/petitioner/buyer/seller…), opposing parties, opposing counsel, related parties (for conflicts), other stakeholders |
| Forum (disputes) | court / tribunal / arbitral institution, bench / judge / arbitrators, case or diary number, filing date, stage, next hearing date, outcome |
| Commercial (transactions) | deal value, currency, counterparty, signing date, closing date |
| Key dates | opened, limitation / deadline dates, hearing dates, closed, archived, dispose-after |
| Status | pending / open / on hold / closed / archived, conflict check result + cleared by + date |
| Governance | default security policy, walls applied, legal hold flag, retention schedule |
| Custom | admin-defined fields (`profile_fields` scope = matter) |

### B.2 Document profile

| Group | Fields |
|---|---|
| Identity | document number, version, name, file type, size, page count, content hash |
| Placement | client, matter, folder(s), related documents |
| Classification | class (pleading, written submission, order/judgment, evidence/exhibit, contract, opinion, research memo, correspondence, email, note, invoice, internal), subclass, status (draft / final / executed / filed / superseded), confidentiality, privilege marker |
| People | author, operator (last editor), created by, checked out by |
| Dates | document date (on the face of the doc), created, modified, filed-in-court date, received date (emails: sent date) |
| Source | upload / email route / migration source + original path |
| Processing | OCR status, index status, language |
| Records | is record, legal hold, retention schedule, dispose-after |
| Versions | version comment, official flag, locked flag |
| Email-only | from, to, cc, subject, message-id, thread id, attachment count, filed by, also filed by |
| Custom | admin-defined fields (`profile_fields` scope = document) |

---

## Appendix C — India-specific requirements

From the market notes the user shared: Indian legal professionals lose 30–59 minutes a day searching for information, and
many top-100 firms still have no central repository (SharePoint, Google Drive, local folders, email, WhatsApp). This shapes the MVP:

- **Migration is the product** for tier-2/3 firms: Google Drive, SharePoint, network share, PST/mbox imports (M11) are launch features, not nice-to-haves.
- **Email from the phone** matters: lawyers work from court on mobile, so the filing address and mailbox-folder sync are in MVP (M5).
- **Data residency and DPDP Act 2023**: India hosting region default; data-processing agreement; personal-data access/erasure requests handled by Records Manager without breaking legal hold.
- **Court metadata**: Indian court and tribunal list as a lookup; case/diary number formats (e.g. `CS(COMM) 123/2024`, `SLP(C) 4567/2023`, `Arb. P. 89/2025`) stored as text with a per-court pattern hint, not validated hard.
- **WhatsApp**: exported chat `.zip`/`.txt` upload parsed as a conversation document (Post; flag as a pilot request to confirm demand).
- **Pricing tiers** for later: firm-level licences for 20+ lawyer firms; this plan does not change the build, only packaging.

---

## Appendix D — User journeys, step by step (MVP behaviour)

Each journey: who, steps, what the system does at each step, rules and edge cases, audit events written, and the acceptance test.
Journey ids (J-xx) are referenced from Appendix A.

### J-01 Firm onboarding (admin, day one)
1. Admin opens the invite link, signs in with SSO (or sets a local password + MFA).
2. Firm setup wizard: firm name, offices, time zone, hosting region (read-only, chosen at provisioning), captions (Client/Matter or Department/Project).
3. Identity: connect IdP; map IdP groups → our groups; choose roles per group; turn on/off just-in-time user creation.
4. Lookups: load defaults (practice areas, matter types, document classes, Indian courts) → edit → save. CSV import allowed.
5. Profile fields: review built-in fields (Appendix B), add custom ones (type, caption, required, lookup, scope).
6. Templates: create at least one matter template (folders, kinds, default security, default filters, saved searches).
7. Security defaults: firm default access, filed-email access option (inherit / participants / me), guest-share defaults (expiry, download), force-filing-in-folder.
8. Retention: create schedules per class (or skip; nothing is ever auto-deleted without review).
9. Mail: verify inbound filing domain (MX/SPF/DKIM shown with copy buttons and a live check), grant M365 admin consent and/or Google OAuth.
10. Invite users (from IdP groups or CSV).
- Rules: wizard can be left and resumed; every step writes `admin.setting_changed`.
- Acceptance: a new firm reaches "first matter created" in under 30 minutes without engineering help.

### J-02 Create client
1. Clients → New client.
2. Fields: client number (auto, editable if admin allows manual), name, client group (parent), type (individual / company / government / other), PAN/GSTIN or other IDs (optional), address, contacts (name, email, phone, role), relationship partner, status, notes.
3. Duplicate check on name and IDs → "possible existing client" list → link or continue.
4. Save → client page opens.
- Rules: client number unique and never reused; merge clients = admin action that re-points matters and keeps both numbers as aliases.
- Audit: `client.created`, `client.updated`, `client.merged`.
- Acceptance: duplicate warning appears for same PAN or near-identical name.

### J-03 Create matter (intake → conflict record → open)
1. Matters → New matter (or from client page).
2. Pick template (last used pre-selected; alphabetical; filter box).
3. Fill Appendix B.1 fields; required ones marked; lookups with type-ahead.
4. Parties: add client role, opposing parties, opposing counsel, related parties (these feed the conflict record).
5. Team: responsible partner (required), members with roles; system shows any wall that would block a chosen member.
6. Security: template default shown (firm-wide / team only / private); can tighten, cannot loosen below firm minimum unless admin.
7. Save as **Pending**. Matter number assigned (`client-seq`). Folders created from template (kinds: with-matter now; optional ones listed as "add later").
8. Conflict check record: who ran it, where (external tool or manual), result (clear / waived with reason / conflict), attachment (search report). Only then "Open matter" is enabled.
9. Open → status Open; team gets "added to matter" notification; matter appears in each member's My Matters.
- Edge cases: template changed later → "re-apply template" adds missing folders only; a member later walled from the client → removed from team with notice to responsible partner.
- Audit: `matter.created`, `matter.conflict_recorded`, `matter.status_changed`, `matter.team_changed`, `matter.security_changed`.
- Acceptance: a pending matter cannot receive documents from mail sync (bounced to Filing inbox with reason) until Open (firm setting can allow).

### J-04 Upload documents
1. In a matter folder: drag files/folders/zip onto the list, or Upload → choose.
2. Upload panel lists each file with progress; large files resume after network drop.
3. Profile step (one dialog for the batch, per-file override): class (required), doc date, status, author (defaults to me), tags, confidentiality, custom fields; apply a saved profile template; "clear profile".
4. If target folder security differs from the batch's chosen security → warning with "use folder security" / "keep mine".
5. Duplicate hits (same hash already in firm) → per file: "file existing document here instead" / "upload anyway as new document" / "skip".
6. Commit → each file gets a document number; AV scan → OCR if image/scanned → text extraction → index → embeddings. Status chip per document: Scanning, Processing, Searchable, Ask-ready, Failed (reason).
7. Activities panel shows the batch: retry failed, undo (moves files to trash), go to folder.
- Rules: blocked types (executables) rejected with reason; size limit (admin); zip expands into folders preserving structure; folder names sanitised; emails inside zip routed to the email pipeline.
- Audit: `document.created` per file (with batch id), `document.duplicate_linked`, `ingest.failed`.
- Acceptance: 1,000-file zip with nested folders loads intact; re-uploading the same zip produces 0 new documents when "skip duplicates" chosen.

### J-05 Profile and re-profile
1. Details panel → Profile tab; inline edit (blur saves, Esc reverts).
2. Mass edit: select N docs → Edit profile → only changed fields applied → preview of affected count → confirm.
3. Moving a document to a different matter re-profiles client/matter and asks about security.
- Rules: blocked under legal hold or record; class change re-computes retention.
- Audit: `document.profile_changed` with before/after per field.

### J-06 Find a document
- **Browse**: Home → recents / My Matters / favourites → matter → Latest documents (all folders) or folder tree.
- **Search**: type in the bar (scope = current matter by default) → results with snippets → filters panel → open → back arrow returns to results.
- **Go to number**: type `85423` or `85423.4` → opens directly (if access).
- **Ask the Firm**: J-25.
- Rules: no result ever reveals a document the user cannot open (counts included).
- Audit: `search.performed` (query text, scope, result count), `document.previewed`.

### J-07 Check out → edit in Word → check in
1. Actions → Check out (optional comment, due date). Padlock appears for everyone; file downloads with name `85423.4 - Title.docx`.
2. User edits locally in Word.
3. Actions → Check in → choose file (name mismatch warning if different document) → version comment (required) → stale-base check ("you checked out v4; latest is v4" OK; if someone force-unlocked and added v5, warn and offer "check in as v6 anyway" or "cancel").
4. New version created; lock released; followers notified.
- Cancel check-out: releases lock, no version.
- Force unlock: owner with unlock right or admin; reason required.
- Reminders: owner gets a reminder at due date and every 3 days after.
- Audit: `document.checked_out`, `document.checked_in`, `document.checkout_cancelled`, `document.force_unlocked`.
- Acceptance: while checked out, another user's "upload new version" is blocked with the holder's name.

### J-08 Versions: compare, restore, official, lock
1. Versions tab → compact list (number, date, author, comment).
2. Compare: pick two → side-by-side text diff.
3. Restore: "make v2 the latest" → creates v6 as a copy of v2 with comment "restored from v2".
4. Official: mark one version official (badge); search shows official by default (setting).
5. Lock version: prevents its deletion or edits to its profile.
6. New version from an older base: "start new version from v3".
- Audit: `version.compared`, `version.restored`, `version.official_set`, `version.locked`, `version.deleted`.

### J-09 Move, copy, also-file
- Move: pick destination → security prompt (match destination / keep current) → same number moves; old location gone.
- Copy: pick destination → new number, current version only → banner "Open the new copy".
- Also file here: pick destination → shortcut created; delete from one place = "unfile" (document stays elsewhere); deleting the document itself needs Admin right and warns "filed in 3 places".
- Rules: cross-matter moves need Edit in both and are blocked by holds; walls checked on destination.
- Audit: `document.moved`, `document.copied` (links new and old numbers), `document.filed`, `document.unfiled`.

### J-10 File email by upload
1. Drag `.eml`/`.msg` (one or many, or a zip / `.mbox`) onto a matter folder.
2. Parse → dedupe check (message-id + hash) → if already filed elsewhere: "add this location" (reference) or "skip".
3. Email appears with attachments as child documents; thread grouping applied.
- Acceptance: a `.msg` with 5 attachments shows 1 email + 5 linked, searchable documents.

### J-11 File email by filing address (forward / BCC)
1. Matter page shows its filing address with a copy button and a "add to contacts" vCard.
2. User forwards or BCCs the address.
3. Receiver checks: sender is an active firm user with Edit on the target (else quarantine + notify sender) → SPF/DKIM pass → size limits.
4. For a forward, the original message is extracted (attached `.eml` or inline-forward parsing) and filed; the forward wrapper is discarded unless it adds text (then filed as a note on the email).
5. Matter tag added to subject only on outgoing copies the user sends later (not on the filed record).
6. Sender gets an optional confirmation email ("Filed to 00042-0007 · view") — per-user setting.
- Edge: wrong address → bounce with "no such matter"; closed matter → quarantine for Records Manager.
- Audit: `mail.filed` (route=address).

### J-12 Connect Outlook mailbox and map a folder
1. Settings → Connected accounts → Connect Microsoft 365 → consent screen (delegated: read/write mail, offline access).
2. Choose a mail folder (tree from Graph; Inbox/Sent/Deleted/Drafts/Junk greyed out) → choose matter folder → options: keep in mailbox (on), file as private (off), map sub-folders (off), copy existing messages (off) → Save.
3. System creates a change subscription; mapped folder renamed with suffix "· filed" (optional setting).
4. User drags mail into it (desktop, web, phone) → change notification → fetch MIME → pipeline → mark "Filed" category → optional move out / delete per options.
5. Health: subscription renewals automatic; failures (token expired, consent revoked) appear in Filing queue and as a notification.
- Disconnect: stops sync; filed mail stays.
- Acceptance: drag on iPhone Outlook files within 5 minutes; disconnect revokes tokens.

### J-13 Connect Gmail and map a label
Same as J-12 with Gmail: OAuth consent → choose label → push notifications via watch → apply label "Filed" after filing.

### J-14 File from a phone with no app
Any of: forward to filing address (J-11) · move to mapped folder/label (J-12/13). Quick-start card explains both in 3 lines.

### J-15 Save an email attachment as a new version
1. Open filed email → attachment → "Save as new version of…" → search document (suggests same-name docs in the matter).
2. Stale-version check (base vs latest) and check-out check (blocked if someone else holds it).
3. Version comment auto-filled: "From email '<subject>' from <sender>, <date>" with link to the email.
- Audit: `version.created` (source=email id).

### J-16 Share externally and request uploads
1. Actions → Share link → recipients (email), expiry (preset or custom ≤ 90 days), passcode (on/off), allow download (on/off), lock to this version (on/off), message.
2. Guest receives email → opens → verifies by email code (+ passcode if set) → sees only shared items; every view/download logged.
3. Upload request: folder → Request files → recipient, max files (default 10), expiry → guest uploads → AV scan → profiled "Received from <guest>" → requester notified.
4. Revoke anytime; admin can see/revoke all.
- Rules: walls checked (cannot share a document you can only view unless you hold Manage); held/record docs can be shared view-only.
- Audit: `share.created`, `share.accessed`, `share.downloaded`, `share.revoked`, `share.upload_received`.

### J-17 Ethical wall
1. Records Manager → Walls → New: type (restricted / exclusion / opposing teams), scope (client, client group, matter, practice group, office), people/groups inside and outside, reason, requested by, effective date.
2. Preview impact: users who will lose access, open check-outs, live share links to revoke.
3. Apply → immediate (ACL epoch bump; search and Ask stop showing items in the same request cycle).
4. Lateral hire activation → checked against exclusion lists → blocked items never appear.
5. Remove / weaken → request → second approver → applied.
- Audit: `wall.created`, `wall.changed`, `wall.removal_requested`, `wall.removal_approved`, `access.denied_by_wall`.
- Acceptance: excluded user's search for an exact title from the walled matter returns 0 and no count.

### J-18 Access request
1. User hits a restricted matter link → "Request access" with reason and duration.
2. Responsible partner (or delegate) approves/denies; options: time-limited (24 h / 48 h / 7 d / custom) or permanent.
3. Expiry removes access automatically and notifies.
- Audit: `access.requested`, `access.granted`, `access.denied`, `access.expired`.

### J-19 Legal hold
1. Records Manager → Holds → New: scope (matter, client, saved search, selection), reason, custodian notes, start date.
2. Effects: delete, purge, disposition, profile edits, version edits blocked; new versions allowed or blocked per hold setting; trash restore allowed.
3. Hold badge on every affected item; release needs a reason.
- Audit: `hold.applied`, `hold.released`, `hold.blocked_action`.

### J-20 Close matter → retention → disposition
1. Responsible partner → Close matter → checklist: check-outs open (must be zero), share links live (revoke all?), pending filing items, final bill reference.
2. Closed → read-only; `dispose_after` computed per document from class schedules.
3. Reopen: audited, reason required.
4. Disposition: monthly digest → Records Manager reviews at matter / folder / document level → approve, defer (with new date) or keep permanently → approved items purged; certificate stored.
- Audit: `matter.closed`, `matter.reopened`, `disposition.approved`, `disposition.deferred`, `document.purged`.

### J-21 Client file export
1. Matter → Export → options: all versions or official/latest only, include emails, include audit trail summary, folder structure.
2. Background job → zip + index CSV + email thread index → download link (expires, export retention).
- Audit: `export.created`, `export.downloaded`.

### J-22 Migrate an archive
1. Admin → Import → source (zip upload, network share via agent, SharePoint, Google Drive, PST/mbox, DMS export with CSV).
2. Map: folder path pattern → client/matter (regex or table), CSV columns → profile fields, author names → users.
3. Dry run → report: files, sizes, mapped/unmapped, unknown users, duplicates, blocked types.
4. Commit in batches (pause/resume); per-file errors with retry.
5. Post: OCR/index/embedding queues; per-matter "search-ready" and "Ask-ready".
- Audit: `import.started`, `import.batch_committed`, `import.file_failed`.

### J-23 Offboard a leaver
1. Admin disables user (or IdP deprovision via SCIM).
2. Their check-outs listed → reassign or force-unlock; their share links → keep or revoke; their mailbox connections → revoked; their My Matters lists shared with others → kept as read-only.
3. Authored documents keep author; history keeps name with "disabled" marker.
- Audit: `user.disabled`, `checkout.reassigned`.

### J-24 Delete and restore
1. Delete (Admin right) → trash; folder delete allowed when empty (or only empty sub-folders).
2. Trash → restore to original location (or choose location if it no longer exists).
3. Purge → Records Manager; blocked by hold/record.
- Audit: `document.deleted`, `document.restored`, `document.purged`.

### J-25 Ask the Firm
1. In a matter: Ask box (scope = this matter; switch to "all matters I can access").
2. Question → retrieval with ACL filter in SQL → ranked passages.
3. Answer pane: matter facts card (if the question is about matter fields) · short extractive answer with numbered citations · list of passages (doc number.version, page, folder) with "open at page".
4. "No relevant material found" when nothing passes the threshold.
5. Feedback: helpful / not helpful + reason (logged for eval).
- Audit: `ask.query` (question, scope, cited ids).

### J-26 Investigate access ("who saw this?")
1. Audit → filter by matter / document / user / action / date → table → CSV export.
2. Access report: "who had access to matter X between dates" (from ACL history, not just views).
- Audit: `audit.exported`.

---

## Appendix E — Icons, badges and states (our own designs, same information)

| State | Where shown | Meaning |
|---|---|---|
| Empty folder / folder with items | tree, lists | distinguishes empty from used folders |
| Folder not inheriting security | tree | its access differs from parent |
| Folder shared externally | tree | has a live guest share |
| Folder shortcut / document shortcut | tree, lists | pointer, not a copy |
| Saved-search folder | tree | dynamic list |
| Checked out (padlock) + holder name | everywhere the doc appears | others cannot add versions |
| Official version | versions list, doc header | version to use |
| Locked version | versions list | cannot be deleted/edited |
| Approved (user, time) | doc header, lists | cleared by any later change |
| Final | doc header | status Final |
| Record | doc header, lists | immutable |
| Legal hold | doc, matter | delete/edit blocked |
| Under wall / restricted | matter header | need-to-know matter |
| Email filed (and "also filed by N") | email list, mail client category | dedupe and visibility |
| Processing chips: Scanning / Processing / Searchable / Ask-ready / Failed | doc lists | pipeline state |
| Guest user / disabled user / wall-restricted user markers | people pickers, team panel | who someone is |
| Expired share link | share list | link no longer works |
| Matter status: Pending / Open / On hold / Closed / Archived | matter header, lists | lifecycle |

---

## Appendix F — Limits and defaults

| Item | iManage | NetDocuments | Ours (MVP default; admin-adjustable where noted) |
|---|---|---|---|
| Recent documents window | 30 days | 40 items | 30 days, paged |
| Recent matters | 20 (30 days) | 40 | 40 |
| Favourite matters | — | 350 | unlimited |
| My Documents list | 5,000 | — | 5,000 |
| Files per upload batch | — | 150 | 10,000 (resumable) |
| Max file size | 64 GB | < 1 GB | 2 GB (admin) |
| Folders per workspace | 10,000 | — | tested to 10,000 |
| Versions per document | — | 32k | unlimited |
| Multi-open | 50 (warn > 20) | — | 20 previews |
| Linked mail folders | sync delays beyond 100 | — | 200 per user |
| Upload request files | 10 | — | 10 (admin) |
| Share link expiry | presets 1–5 days, ≤ 90 days | optional | presets 1/3/7/30 days, ≤ 90 days |
| Timeline default range | 3 months | — | 3 months |
| Retention digest | — | every 60 days | every 30 days |
| Session idle timeout | — | — | 8 h |
| Filing confirmation latency (mail sync) | — | — | ≤ 5 min p95 |

---

## Appendix G — Role × action permission matrix (defaults)

Roles: **Adm** firm admin · **RM** records manager · **Ptr** partner · **Assoc** associate · **PL** paralegal · **Staff** · **RO** read-only · **Guest**.
Access levels on an item: View < Download < Edit < Manage < Admin; Deny overrides all. A role grants *capabilities*; the item's access level grants *rights on that item*. Both are needed.

| Action | Needs item level | Adm | RM | Ptr | Assoc | PL | Staff | RO | Guest |
|---|---|---|---|---|---|---|---|---|---|
| Create client | — | ✓ | ✓ | ✓ | – | – | – | – | – |
| Create matter | — | ✓ | ✓ | ✓ | ✓* | – | – | – | – |
| Open matter (after conflict record) | Manage | ✓ | ✓ | ✓ | – | – | – | – | – |
| Close / reopen matter | Manage | ✓ | ✓ | ✓ | – | – | – | – | – |
| Create folder (non-template) | Edit on parent | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – | – |
| Create firm-visible ("public") folder | Edit | ✓ | ✓ | ✓ | – | – | – | – | – |
| Upload / new version / check-in | Edit | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – | upload request only |
| Preview / view | View | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | shared items |
| Download / print / export | Download | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | if link allows |
| Edit profile / rename / approve | Edit | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – | – |
| Move / copy / also-file / unfile | Edit (both ends) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – | – |
| Delete to trash | Admin | ✓ | ✓ | ✓ | – | – | – | – | – |
| Delete a version | Admin | ✓ | ✓ | – | – | – | – | – | – |
| Purge from trash | — | – | ✓ | – | – | – | – | – | – |
| Force unlock | Manage | ✓ | ✓ | ✓ | – | – | – | – | – |
| Change access / share internally | Manage | ✓ | ✓ | ✓ | ✓ | – | – | – | – |
| Create external share / upload request | Manage | ✓ | ✓ | ✓ | ✓ | ✓* | – | – | – |
| Create / change walls | — | ✓ | ✓ | – | – | – | – | – | – |
| Approve wall removal (second person) | — | – | ✓ | ✓ (GC/MP only) | – | – | – | – | – |
| Approve access request | Manage | ✓ | ✓ | ✓ | – | – | – | – | – |
| Declare / undeclare record | Edit / — | ✓ | ✓ | ✓ / – | – | – | – | – | – |
| Apply / release legal hold | — | – | ✓ | – | – | – | – | – | – |
| Approve disposition | — | – | ✓ | – | – | – | – | – | – |
| View audit (firm) | — | ✓ | ✓ | – | – | – | – | – | – |
| View document history | View | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – |
| Ask the Firm | View | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – |
| Connect own mailbox / map folders | Edit on target | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – | – |
| Admin console (lookups, templates, users) | — | ✓ | partial (retention) | – | – | – | – | – | – |

`*` firm setting. Every cell is configurable per firm; this is the shipped default.

---

## Appendix H — Settings catalog

**User settings**: landing tab · open behaviour (preview / download) per type · list vs grid default · columns per view · recents window · email digest frequency (off / daily / weekly) · filing confirmation emails on/off · connected mailboxes and mappings · notification channels per event · reset layout · time zone · date format.

**Firm settings**: captions · matter number format · client number format (auto/manual) · force filing in folder · flexible folders (allow ad-hoc folders) · who can create matters · pending matters accept documents (yes/no) · default matter access · filed-email access (inherit / participants / me, user may override yes/no) · email filing allowed into (any folder / email-kind folders only) · required fields on email filing · mail sync on/off per provider · sender quarantine policy · confirmation email default · share-link defaults (expiry presets, max expiry, passcode required, download default, guest verification) · upload request max files · max upload size · blocked file types · OCR languages (English + Hindi + others) · retention digest frequency · export link expiry · session timeout · MFA required for local accounts · IP allowlist (Post) · save-dialog security warning on/off · multi-version permission edit on/off · Ask on/off per matter type · audit export permission.

**Admin catalogs**: users · groups (internal / guest) · roles · lookups · profile fields · classes and subclasses (retention, default status) · folder kinds · matter templates · profile templates · retention schedules · walls · holds · webhooks · service accounts · mail domains · import mappings.

---

## Appendix I — Notifications catalog

| Event | Who | Channel default |
|---|---|---|
| Added to a matter team | the member | in-app + email |
| New document / version / profile change in followed matter or document | followers | in-app; digest by email |
| Document you hold checked out past due date | holder | email |
| Your check-out force-unlocked | holder | in-app + email |
| Access request awaiting you | approver | in-app + email |
| Access granted / denied / expiring in 24 h / expired | requester | in-app + email |
| Wall applied affecting you | affected user | in-app (no matter name if exclusion) |
| Wall removal awaiting second approval | approvers | in-app + email |
| Legal hold applied / released on your matter | team | in-app |
| Email filed (confirmation) | filer | email (opt-in) |
| Email quarantined (unknown sender / closed matter / no rights) | filer, RM | in-app + email |
| Mailbox connection failing | user | in-app + email |
| Share link viewed / downloaded (first time) | link creator | in-app |
| Upload request received | requester / default recipient | in-app + email |
| Shared folder changed by guest | subscribers | email |
| Import batch finished / failed | admin | in-app + email |
| Retention digest | RM | email |
| Unusual activity alert | admin, RM | email |
| Background job finished (apply security to contents, export, mass edit) | initiator | in-app (bell) |

---

## Appendix J — Audit event catalog

All rows: `event_id, ts, actor_user_id, actor_kind (user/service/guest), on_behalf_of, ip, user_agent, firm_id, matter_id, document_id, version, action, details (jsonb), result (ok/denied/error)`.

| Area | Events |
|---|---|
| Session | `auth.login`, `auth.logout`, `auth.failed`, `auth.mfa_challenge`, `session.expired` |
| Admin | `admin.setting_changed`, `user.created`, `user.disabled`, `user.role_changed`, `group.changed`, `lookup.changed`, `template.changed`, `field.changed` |
| Client / matter | `client.created`, `client.updated`, `client.merged`, `matter.created`, `matter.updated`, `matter.conflict_recorded`, `matter.status_changed`, `matter.team_changed`, `matter.closed`, `matter.reopened`, `matter.template_reapplied` |
| Document | `document.created`, `document.previewed`, `document.downloaded`, `document.printed`, `document.text_copied`, `document.profile_changed`, `document.renamed`, `document.moved`, `document.copied`, `document.filed`, `document.unfiled`, `document.related`, `document.approved`, `document.marked_final`, `document.deleted`, `document.restored`, `document.purged`, `document.duplicate_linked` |
| Version / lock | `version.created`, `version.compared`, `version.restored`, `version.official_set`, `version.locked`, `version.deleted`, `document.checked_out`, `document.checked_in`, `document.checkout_cancelled`, `document.force_unlocked` |
| Email | `mail.filed` (route), `mail.deduped`, `mail.quarantined`, `mail.refiled`, `mail.attachment_saved_as_version`, `mailbox.connected`, `mailbox.disconnected`, `mailbox.mapping_changed` |
| Security | `access.changed`, `access.applied_to_children`, `access.requested`, `access.granted`, `access.denied`, `access.expired`, `access.denied_by_wall`, `wall.created`, `wall.changed`, `wall.removal_requested`, `wall.removal_approved` |
| Records | `record.declared`, `record.undeclared`, `hold.applied`, `hold.released`, `hold.blocked_action`, `retention.computed`, `disposition.approved`, `disposition.deferred` |
| Sharing | `share.created`, `share.accessed`, `share.downloaded`, `share.revoked`, `share.expired`, `share.upload_received` |
| Search / Ask | `search.performed`, `search.saved`, `ask.query`, `ask.feedback` |
| Bulk / jobs | `import.started`, `import.batch_committed`, `import.file_failed`, `export.created`, `export.downloaded`, `mass_edit.applied`, `audit.exported` |
