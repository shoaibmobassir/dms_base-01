# Mike → DMS Knowledge Base — Feature Gap Audit

**Date:** 2026-09-20  
**Status:** Product-research audit (clean-room)  
**Scope:** What Mike (AGPLv3) can do as a product that DMS knowledge_base does not yet deliver as a working end-to-end capability.

---

## 0. Clean-room notice (mandatory)

Mike at `/Users/shoaibmobassir/Desktop/Experiments/Legal_Maal /mike` is **AGPLv3**. This document is **product research only**.

| Allowed here | Forbidden |
|--------------|-----------|
| Problems Mike solves, users, outcomes | Copying / porting / rewriting Mike source |
| Capability categories and workflows | Copying Mike SQL, APIs, UI, tests, comments, assets |
| Technology-independent requirements | Using Mike as a coding template |

Any future implementation must follow:

```text
Mike observation → independent requirement → our design → our code
```

Record Mike-inspired work in `legal-memory-retrieval/docs/legal/IP_ORIGIN_RECORD.md` before coding.  
This audit is **not legal advice**.

---

## 1. What was compared

| Side | Paths examined (product surface) |
|------|----------------------------------|
| **Mike** | `README`, `docs/*`, frontend app pages, backend route/entity inventory, Word add-in README, docker-compose service set, e2e suite names |
| **DMS KB** | `legal-memory-retrieval/` (primary product), `static` SPA, routers/modules/schema, `docs/*` plans, `apex-dms/` (early Go shell), `doc-search/` (companion), `word-addin/manifest.xml`, `dummy-firm/` |

**Method:** Compare *user-visible / operational capabilities*, not line-of-code parity.  
A DMS folder or router that exists but is in-memory, UI-less, fake-only, or demo-seeded is scored **Partial**, not **Present**.

### Status legend

| Tag | Meaning |
|-----|---------|
| **Absent** | No meaningful equivalent in DMS KB |
| **Partial** | Some backend/library/plan exists; not a complete working product surface |
| **Present (narrower)** | Exists in DMS but with smaller scope, weaker UX, or firm-corpus focus |

---

## 2. Executive verdict

Mike is a **full legal AI workspace product**: auth + multi-user org, Next.js app, document library, project workspaces, assistant chat, reusable workflows, tabular review UI, settings (BYOK/models/connectors/MFA/privacy), CourtListener research UX, production Word add-in, and a self-hosted stack (Auth + object storage + mail).

DMS knowledge_base is strongest as a **retrieval-first firm memory system** (hybrid ACL-filtered retrieval, evals, Ask/Chat backends, matter/project/document APIs, Phase-0 sync substrate). Many Mike-like *capability names* appear in DMS (tabular, workflows, caselaw, Word, BYOK, sources), but most are **not yet a shippable product loop** comparable to Mike’s working UI + persistence + auth.

**Rough gap shape:** Mike ≫ DMS on product completeness / UX / auth / Word / workflows / library / connectors / settings.  
DMS ≫ Mike on measured firm-corpus retrieval science (eval gates, hybrid engine v2, matter scope, paraphrase experiments)—noted only for context; this doc focuses on **Mike capabilities missing from DMS**.

---

## 3. Capability matrix (Mike → DMS)

### A. Platform, identity, tenancy

| Mike capability (product level) | DMS status | Gap summary |
|---------------------------------|------------|-------------|
| Email/password signup, login, password reset, email confirmation (local mail capture) | **Absent** | DMS uses `X-Member-Id` / API keys; no end-user account lifecycle |
| OAuth / session cookies for browser app | **Absent** | Header/API-key identity only |
| MFA enroll / challenge / verify / login assurance | **Absent** | No MFA product surface |
| User profiles, onboarding (profile + practice) | **Absent** | Sidebar shows a static demo user |
| Organisation / firm membership on profile | **Partial** | Corpus has members/matters; no self-serve org onboarding |
| Per-user encrypted BYOK keys (Anthropic/OpenAI/Gemini/Ollama/OpenRouter/etc.) with Settings UI | **Partial** | `KeyVault` + `model_router` exist; no Settings/BYOK UI or durable `user_api_keys` product tables in main schema |
| Per-user / per-task model preference routing UI | **Partial** | Router code exists; no Models settings UX |
| Privacy / data export / user data cleanup | **Absent** | No GDPR-style export/delete account flows |
| Appearance / personalisation / feature flags settings | **Absent** | No settings app area |
| Security settings (password, MFA-on-login) | **Absent** | — |
| Support page / contact channel | **Absent** | — |
| Full Next.js product shell + design system | **Partial** | Vanilla SPA at `/ui`; functional but not a full multi-page product app |

### B. Document library & file management

| Mike capability | DMS status | Gap summary |
|-----------------|------------|-------------|
| Firm **Library** (files + nested folders) separate from matters/projects | **Absent** | Documents are matter/project-scoped corpus/API; no Library product |
| **Templates** library with template folders | **Absent** | — |
| Upload → versioned storage → browse/download as primary UX | **Partial** | Upload batch + versions APIs exist; weaker library UX than Mike |
| Soft-deleted versions retained in export trail | **Partial** | Versioning exists; Mike-style export trail UX incomplete |
| In-browser document editing with revision records (`document_edits`) | **Absent** | DMS generates tracked DOCX; no collaborative edit history product |
| DOC/DOCX→PDF conversion path (LibreOffice-oriented ops) | **Absent** | Not a first-class DMS ops feature |
| Spreadsheet document handling as first-class source | **Partial** | Review exports XLSX; not a full spreadsheet ingest/review UX |

### C. Projects, matters, clients, people, teams

| Mike capability | DMS status | Gap summary |
|-----------------|------------|-------------|
| Projects list + project workspace (folders, assistant, tabular reviews nested) | **Partial** | Projects API + SPA tabs (Overview/Documents/Activity); no nested project assistant/tabular product routes |
| Project sharing with other users | **Absent** | No share ACL product |
| Matters / clients / people / teams browsable pages | **Present (narrower)** | UI + APIs exist; largely corpus-backed firm memory, not full CRM lifecycle |
| Court deadlines / tasks surface | **Present (narrower)** | `/ui/tasks` + API; thinner than a full matter calendar product |
| Live activity / history of user work | **Partial** | Activity feed exists; Mike “History” of chats/work is richer |
| Knowledge vault (arguments / precedents / clauses UX) | **Partial** | Knowledge API + UI; some content appears seed/demo-like vs editable institutional bank |

### D. Assistant / chat

| Mike capability | DMS status | Gap summary |
|-----------------|------------|-------------|
| Dedicated Assistant home + multi-session chat UI | **Partial** | Backend chat sessions + SSE agent are strong; frontend chat UX still incomplete (see existing gap note) |
| Project-scoped assistant (chat bound to project docs) | **Partial** | Tools can search/attach docs; no first-class project-assistant workspace like Mike |
| Mid-turn interactive prompts (`ask_inputs`-style cards) | **Partial** | Backend event concepts exist; UI cards incomplete |
| Citation pills + sources tray + side-panel quote highlight | **Partial** | Backend verification strong; frontend citation UX incomplete |
| Generated `.docx` / `.xlsx` artifact cards in chat | **Partial** | Generation tools exist; UI cards incomplete |
| Chat export | **Absent** | No chat export product |
| Tabular-review-scoped chat | **Absent** | No review↔chat linkage product |

*See also:* `legal-memory-retrieval/docs/assistant_chatbot_deep_gap_analysis.md` (chat UI checklist).

### E. Workflows / playbooks / quick actions

| Mike capability | DMS status | Gap summary |
|-----------------|------------|-------------|
| Workflow catalog UI (assistant + tabular-review workflow types) | **Partial** | YAML catalog + run API (in-memory run store); **no** Workflows nav/UI |
| System workflow pack sync from external workflows repo | **Absent** | Mike syncs packaged system workflows; DMS has 3 local YAML files only |
| Workflow add-ons / packs | **Absent** | — |
| Workflow sharing / hide / default installations | **Absent** | — |
| Open-source workflow submission flow | **Absent** | — |
| Quick actions (e.g. proofread / compare) especially in Word | **Absent** | — |
| Persistent workflow execution history UI | **Absent** | Runs not durable in Postgres schema |

### F. Tabular / matrix document review

| Mike capability | DMS status | Gap summary |
|-----------------|------------|-------------|
| Tabular reviews list + detail UI | **Absent** (API only) | `/api/tabular` + service; `_REVIEWS_DB` in-memory; **not** in schema; **no** `/ui` nav |
| Column schema builder UX | **Absent** | API accepts columns; no builder UI |
| Cell confidence / reasoning / citation chips in matrix UI | **Partial** | Service returns structured cells; no matrix UI |
| Human override / patch cell | **Partial** | Patch endpoint pattern exists; no UI |
| Spreadsheet export | **Partial** | Exporter + tests exist |
| Project-nested tabular reviews | **Absent** | — |
| Tabular review sharing | **Absent** | — |
| Chat inside a tabular review | **Absent** | — |

### G. Case law / legal research

| Mike capability | DMS status | Gap summary |
|-----------------|------------|-------------|
| CourtListener live citation verify + opinion search in assistant | **Partial** | Parser + client + router exist; no polished research panels / settings token UX |
| Optional **bulk** CourtListener indexes (local citation/cluster tables + opinion JSON) | **Absent** | No bulk index tables / import path in DMS |
| Per-user CourtListener API key in BYOK settings | **Absent** | — |
| Legal-research feature toggle on profile | **Absent** | — |

### H. Connectors / sync / MCP

| Mike capability | DMS status | Gap summary |
|-----------------|------------|-------------|
| Settings → Connectors product UX | **Absent** | DMS has `/api/sources` Phase 0 (flagged); no Settings connectors UI |
| Real Google Drive / Microsoft Graph (OneDrive/SharePoint) OAuth connectors | **Absent** | DMS: `FakeConnector` only; plan in `docs/universal-document-sync-engine-plan.md` |
| Incremental sync with durable cursors + webhook wake | **Partial** | Sync engine + tables Phase 0; not production providers |
| Source ACL intersection with firm ACL in retrieval | **Partial** | Source permissions stored; matter-trust still default |
| **MCP connectors** (user MCP servers, OAuth, tool audit) | **Absent** | Entire MCP product area missing from DMS |
| Source-documents bridging into chats/reviews | **Partial** | Chat can search firm records; not Mike’s connector-fed library model |

### I. Microsoft Word add-in

| Mike capability | DMS status | Gap summary |
|-----------------|------------|-------------|
| Production Word task-pane add-in (React, webpack, sideload scripts, e2e) | **Absent / stub** | DMS: `manifest.xml` + static `word-taskpane.html`; Mike: full add-in package |
| Word-only chat history store (separate from web) | **Absent** | — |
| Apply suggested revisions as tracked changes **inside Word**, accept/reject | **Partial** | Server can emit tracked DOCX; Word apply/accept UX not productized |
| Attach library docs + run workflows from Word | **Absent** | — |
| Quick actions in Word (proofread, compare, …) | **Absent** | — |
| Auth handoff ticket web→Word | **Partial** | Handoff service + `/api/word` endpoints exist; no full add-in client |
| Device-local vs cloud chat storage option | **Absent** | — |

### J. Trust, audit, exports

| Mike capability | DMS status | Gap summary |
|-----------------|------------|-------------|
| Tamper-evident project export manifests (hashes + optional Ed25519) | **Partial** | Manifest signer + audit verify endpoint; not full Mike export UX |
| Immutable audit event stream for user/security actions | **Partial** | Some audit/export pieces; not full auth/security audit product |
| Signed download tokens for object storage | **Absent** as product | Mike-oriented download signing story not mirrored |

### K. Ops, quality, packaging

| Mike capability | DMS status | Gap summary |
|-----------------|------------|-------------|
| One-command full stack: app + Auth + Postgres + object store + mail | **Partial** | DMS: Postgres + MinIO (+ Redis elsewhere); no Auth/mail stack |
| Playwright e2e covering auth, projects, tabular, workflows | **Absent** | DMS: pytest-heavy; no Mike-class browser e2e suite |
| Frontend unit + mutation/load harness culture | **Absent** | — |
| Documented production deployment to managed Auth + R2 | **Partial** | Local compose + scripts; not Mike-level deployment guide set |
| Accessibility e2e coverage | **Absent** | — |

---

## 4. Detailed gap catalog (requirements language)

Each item below is phrased as a **technology-independent requirement** so future work can be designed independently (do **not** implement by reading Mike source).

### 4.1 Identity & security product

1. **Account lifecycle** — Users can register, verify email, sign in, reset password, and sign out.
2. **Session security** — Browser sessions are authenticated without shipping long-lived secrets in localStorage as the only model; MFA optional/required by policy.
3. **Tenant/org membership** — Users belong to an organisation; firm data is scoped accordingly.
4. **BYOK vault UX** — Users store provider API keys encrypted at rest and select models per task class (chat, review, extract, draft).
5. **Privacy controls** — Users can export and/or delete their personal data per policy.
6. **Admin/security settings** — Password, MFA, and session policies are configurable in-product.

### 4.2 Document library & templates

7. **Firm library** — Users manage a firm-wide (or shared) document library with nested folders independent of a single matter.
8. **Templates** — Users store and organise reusable drafting templates.
9. **Version + edit trail** — Document versions are immutable; suggested edits and accept/reject trails are queryable and exportable.
10. **Format conversion** — Common office formats can be normalised for preview/review pipelines.

### 4.3 Collaboration & sharing

11. **Share projects / reviews / workflows** — Owners grant access to colleagues without giving blanket firm admin rights.
12. **Activity & history** — Users see their recent chats, reviews, and document actions in a dedicated history surface.

### 4.4 Assistant product completeness

13. **Chat UX parity** — Session switcher, SSE streaming, tool status pills, citation badges, sources tray, side-panel quote jump, artifact download cards.
14. **Project assistant** — Chat can be opened in a project context with that project’s documents as the default universe.
15. **Interactive mid-turn inputs** — Assistant can request missing docs or choices without breaking the turn.
16. **Chat export** — Users can export a conversation for matter files.

### 4.5 Workflows product

17. **Workflow studio / catalog UI** — Browse, configure inputs, run, and inspect multi-step playbooks.
18. **Durable run history** — Executions persist with inputs/outputs/artifacts.
19. **Packaged system playbooks** — Curated firm/system playbooks can be installed/updated without editing code.
20. **Sharing & add-ons** — Workflows can be shared; optional packs extend the catalog.
21. **Quick actions** — One-click actions for common drafting/review tasks (especially from Word).

### 4.6 Tabular review product

22. **Matrix UI** — Create reviews, define columns, run extraction, browse cells with confidence/citations.
23. **Human-in-the-loop** — Edit/override cells; track review state.
24. **Persistence** — Reviews/rows/cells stored durably (not process memory).
25. **Export & share** — Download workbooks; share review with teammates.
26. **Review chat** — Optional chat scoped to a review’s documents/cells.

### 4.7 Research product

27. **Case-law tools in UX** — Verify citations / fetch opinions with clear status in assistant and settings.
28. **Optional offline/bulk case data** — Deployments may preload citation/cluster indexes for scale/privacy.
29. **User research tokens** — Users may supply their own research-API credentials.

### 4.8 Connectors & extensions

30. **Real cloud drive connectors** — OAuth connect to Drive / OneDrive / SharePoint; incremental sync into firm storage + index.
31. **Connector settings UX** — Connection health, scopes, last sync, errors, disconnect.
32. **Permission intersection** — Source-system ACLs and firm matter ACLs both constrain retrieval.
33. **MCP tool connectors** — Users attach MCP servers; tools are discoverable, OAuth where needed, audited.

### 4.9 Word product

34. **Ship a real Word add-in** — Sideloadable task pane with auth handoff to the firm backend.
35. **In-Word tracked edit loop** — Propose → apply as tracked changes → accept/reject in Word.
36. **Word workflows & quick actions** — Same playbook/actions available from Word.
37. **Word-local conversation store** — Word chats do not collide with web chat history unless intended.

### 4.10 Platform packaging

38. **Auth + mail + object storage in local stack** — Developers can run a complete identity-capable environment locally.
39. **Browser e2e gates** — Critical paths (auth, project, chat, tabular, workflows) covered by automated UI tests.
40. **Deployment runbooks** — Production Auth, storage, secrets, migrations, and release jobs documented for operators.

---

## 5. “Exists in DMS but not Mike-complete” (do not treat as done)

These are easy to over-count as parity. Treat as **debt**, not checkmarks:

| Area | What DMS has today | What’s still missing vs Mike product |
|------|--------------------|--------------------------------------|
| Chat agent | Sessions, tools, SSE, citation verify | Full chat UI, project assistant, artifact cards |
| Tabular | Service + API + xlsx exporter | Durable schema, matrix UI, sharing, review chat |
| Workflows | 3 YAML playbooks + engine + API | Catalog UI, sync packs, shares, durable runs |
| BYOK / models | KeyVault + model_router | Settings UI, per-user persisted keys/preferences |
| Caselaw | Parser + CourtListener client | Bulk indexes, settings tokens, research UX |
| Word | Handoff API + static taskpane + tracked DOCX generator | Full add-in, in-Word accept/reject, workflows |
| Sources | Phase-0 tables + FakeConnector + sync engine | Real providers, OAuth UX, ACL intersection |
| Projects | Folders, versions, activity, export hooks | Nested assistant/tabular, sharing |
| Auth | API keys + optional AUTH_ENABLED | Signup, MFA, sessions, org onboarding |
| Audit/export | Manifest signer pieces | Full project export UX + security audit stream |

---

## 6. DMS areas that are *not* Mike gaps (context only)

Mike-absent or weaker relative strengths of DMS (so the audit is not mistaken for “Mike is strictly a superset”):

- Eval-gated hybrid retrieval (BM25 + vector + metadata + graph + fusion policy + CE) on a frozen firm corpus  
- Hard matter scope / matter resolver / paraphrase & Harbour benchmarks  
- ACL-before-rank discipline as a first principle  
- Deep retrieval observability / diagnose tooling  
- Companion `doc-search` and experimental plans (`paraphrase-resolution-experiments.md`, sync plan)

These do **not** close the product gaps in §3–§4.

---

## 7. Repo topology gap (product packaging)

| Mike | DMS knowledge_base |
|------|--------------------|
| Single product monorepo: `frontend` + `backend` + `word-addin` + compose | Split: `legal-memory-retrieval` (main), early `apex-dms` (Go matter shell), `doc-search`, stub `word-addin`, `dummy-firm` corpus |
| Auth + storage + mail in compose | Postgres/Redis/MinIO-oriented; no Auth/mail product stack |
| Playwright e2e product suite | Pytest + retrieval evals |

---

## 8. Suggested independent build priority (requirements → design)

Not a mandate—ordered by typical lawyer-product dependency:

1. **Identity + sessions + org** (blocks trustworthy multi-user everything)  
2. **Chat UI completion** (backend already ahead of UI)  
3. **Durable tabular + workflows UI** (turn Partial APIs into products)  
4. **Library / templates** (document work without only matter dumps)  
5. **Real source connectors** (execute sync plan beyond Fake)  
6. **Word add-in v1** (auth handoff + chat + insert/redline)  
7. **Case-law UX + optional bulk**  
8. **MCP connectors** (power-user extension)  
9. **Sharing, privacy export, e2e, deployment hardening**

For every item: write a clean requirement + IP_ORIGIN entry **before** implementation. Prefer “better than Mike for Harbour/FirmOS users,” not visual or structural cloning.

---

## 9. Related internal docs

| Doc | Role |
|-----|------|
| `legal-memory-retrieval/docs/legal/IP_ORIGIN_RECORD.md` | Provenance log for Mike-inspired features |
| `legal-memory-retrieval/docs/assistant_chatbot_deep_gap_analysis.md` | Chat UI deep gaps |
| `docs/universal-document-sync-engine-plan.md` | Connector/sync plan (clean-room) |
| `firmos_production_actionable_plan.md` | Broader FirmOS production plan |
| `.cursor/rules/agpl-cleanroom.mdc` | Mandatory clean-room protocol |

---

## 10. Audit method & limits

**In scope:** Product pages, docs feature claims, entity/capability inventories, DMS routers/UI/schema maturity.  
**Out of scope:** Line-by-line code comparison, copying Mike designs, declaring legal non-infringement.  
**Limits:** Maturity judgments use presence of durable schema, UI routes, real providers, and e2e—not marketing names. Re-run this audit after major DMS product milestones.

---

*End of audit.*
