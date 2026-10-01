# 03 — Prune the frontend

Closes: B5, B7, and the "no backend behind it" table in `AUDIT.md`.

## Remove

Pages: `ProjectsPage`, `ProjectDetailPage`, `ActivityPage`, `AuditPage`, `StrategyPage`,
`DueDiligencePage`, `KnowledgeGapsPage`, `KnowledgeManagementPage`, `ExperiencePage`,
`StaffingPage`, `TransitionsPage`, `KnowledgePage`, `PrecedentsPage`, `PermissionsPage`,
`SimilarMattersPage`, `TimelinesPage`.

Components/modules: `CreateProjectModal`, `api/projects.ts`, `api/activity.ts` (if unused after),
`api/knowledge.ts` precedents/clauses calls, `data/mock.ts`, `data/firm.ts`, `KnowledgeGraph` if unused.

Matter-detail tabs with no data: Matter DNA, Precedents, Drafts, Emails, Knowledge, Audit.

Shell references: sidebar entries, command-palette entries ("Projects", "Activity", "Create
project"), topbar breadcrumbs and "My activity", fake notifications bell.

## Resulting navigation

- **Workspace:** Home · Ask the Firm · Chat · Matters · Clients · Documents · People · Deadlines
- **Knowledge:** Arguments
- **Manage:** Teams · Data Sources · Settings

## Identity

- Personas come from `GET /api/people` (real members). The switcher is shown only when the backend
  reports `auth_enabled = false` (`GET /api/system/info`).
- Firm name/descriptor from `GET /api/system/firm`.

## Done when

- `grep -r "mock\|Apex Chambers\|Aryan\|MEM-00049" frontend/src` → nothing.
- `npm run build` green; no route renders a static "not available from the API" empty state.
