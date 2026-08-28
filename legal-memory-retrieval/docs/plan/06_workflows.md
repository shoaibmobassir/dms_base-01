# Feature: Legal Workflows — Reusable Structured AI Tasks

**Sprint:** 10  
**Priority:** P1  
**Mike observation (product level):** Legal platforms let lawyers run named, pre-built AI task sequences (like "Draft Position Paper" or "Matter Summary") so the same quality of AI-guided work is available to everyone on the team without each person crafting their own prompts.  
**Mike source used as coding basis:** NO  
**Date:** 2026-08-28

---

## Problem

Currently `POST /ask` handles free-form questions. But many legal tasks are structured and repeatable: summarise this matter, draft a position on these issues, compare two matters, extract key dates from a document set. Without a workflow layer, every user improvises a prompt and gets inconsistent results.

---

## User need

A partner wants every associate to run the same structured "Matter Briefing" workflow for every new engagement. The workflow asks: what is the matter, what practice area, what are the open issues. It retrieves the relevant firm precedents, then produces a consistent briefing memo outline.

---

## Requirements

1. A **workflow catalog** — a list of available workflows, each with an `id`, `title`, `description`, and a structured `steps` list
2. Workflows live as YAML files in `app/workflows/catalog/` — no database for catalog (catalog is code-controlled)
3. `GET /workflows` returns the catalog list
4. `POST /workflows/run` runs a workflow: takes `workflow_id`, `inputs` (key-value), `member_id`
5. Each step in a workflow is one of: `retrieve(query_template)`, `ask(query_template)`, or `compose(template)` — no arbitrary code execution
6. Steps can reference outputs of previous steps using `{{step_N.answer}}` syntax
7. Results are persisted to `workflow_runs` table and retrievable
8. Workflows view in UI shows the catalog, inputs for the selected workflow, and run history

---

## Our independent design decisions

**Catalog format (YAML, not code):**
```yaml
id: matter-briefing
title: Matter Briefing
description: Retrieves precedents and produces a structured briefing outline for a new matter.
inputs:
  - name: matter_id
    label: Matter ID
    type: string
    required: true
  - name: practice_area
    label: Practice Area
    type: enum
    options: [M&A, Arbitration, Insolvency, Tax, Employment, Regulatory, Disputes, Banking]
steps:
  - id: retrieve_precedents
    type: retrieve
    query: "Matters involving {{inputs.practice_area}} with similar issues to {{inputs.matter_id}}"
  - id: draft_briefing
    type: ask
    query: "Summarise the firm's experience in {{inputs.practice_area}} based on these precedents. Focus on outcomes and key legal positions."
  - id: compose_output
    type: compose
    template: |
      # Matter Briefing — {{inputs.matter_id}}
      ## Relevant Precedents
      {{steps.retrieve_precedents.hits_summary}}
      ## Firm Position
      {{steps.draft_briefing.answer}}
```

**Step types:**
- `retrieve` — calls `retrieve()` internally, returns `hits`
- `ask` — calls `answer_question()` internally, returns `answer`, `citations`, `abstained`
- `compose` — renders a Jinja2 template from prior step outputs (no LLM call)

**Schema:**
```sql
CREATE TABLE workflow_runs (
    run_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    member_id TEXT,
    session_token TEXT,
    inputs JSONB NOT NULL DEFAULT '{}',
    steps_output JSONB NOT NULL DEFAULT '{}',
    final_output TEXT,
    status TEXT NOT NULL DEFAULT 'running',   -- running | complete | error
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
```

**Built-in workflows (Sprint 10 launch set):**
1. `matter-briefing` — summarise firm precedents for a practice area
2. `position-memo` — draft firm's position on a named issue in a matter
3. `experience-search` — find all lawyers with experience in a practice area, ranked by matter count
4. `cross-matter-comparison` — compare two matters side-by-side on legal issues and outcomes

**What this is NOT:**
- Not an agent (no loop, no tool-calling LLM)
- Not Mike's workflow system (independent YAML-driven pipeline, different step types, different schema)
- Not arbitrary code execution — steps are typed and constrained

---

## Files affected

- New directory: `app/workflows/`
- `app/workflows/runner.py` — step executor
- `app/workflows/catalog/` — YAML files for each built-in
- `app/api/main.py` — 2 new routes: `GET /workflows`, `POST /workflows/run`
- Migration: `20260828_02_workflow_runs.sql`
- `static/app.js` — Workflows view

---

## PM Gate

**Status:** PENDING

- [ ] Feature doc written ✓
- [ ] IP_ORIGIN_RECORD entry required (Mike-inspired — workflows concept)
- [ ] Catalog format designed independently (YAML steps, not Mike's TS objects) ✓
- [ ] Schema designed independently ✓
- [ ] No arbitrary code execution in step runner ✓
- [ ] Dependency check: PyYAML (MIT) + Jinja2 (BSD-3-Clause) — both clear
- [ ] Test plan: run `matter-briefing` workflow, assert each step produces output, assert final_output non-empty
