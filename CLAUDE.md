# Apex Chambers — DMS Knowledge Base

## Project overview

Two sub-projects:
- `dummy-firm/` — synthetic law-firm corpus generator (frozen at v2: 1000 matters, 38,232 documents)
- `legal-memory-retrieval/` — retrieval + answer API (Sprint 8 complete)

See `legal-memory-retrieval/CLAUDE.md` for retrieval sprint rules and eval gates.

---

## AGPL CLEAN-ROOM PROTOCOL — MANDATORY

The repository at `/Users/shoaibmobassir/Desktop/Experiments/Legal_Maal /mike` is an
**AGPLv3-licensed project** used as **product research only**.

### What this means for every task

**NEVER:**
- Copy, translate, port, rewrite, or transform any Mike source code
- Use Mike as a coding template (renaming variables/functions is not sufficient)
- Copy Mike SQL schemas, migrations, API implementations, or test cases
- Copy Mike UI components, layouts, assets, icons, or documentation prose

**ALWAYS:**
- Convert any Mike observation to a technology-independent requirement first
- Design our schema, API, and UI independently from that requirement
- Record Mike-inspired features in `legal-memory-retrieval/docs/legal/IP_ORIGIN_RECORD.md`
- Audit new dependency licenses before adding them

### The only safe pipeline

```
Mike (product research)
        │
        │  What problem? Who is the user? What outcome?
        ▼
Technology-independent requirement
        │
        │  Independent design — our names, our structure
        ▼
Our code (never traceable to Mike source)
```

### Stop conditions

Stop immediately and ask for human review if:
- Asked to "copy", "rewrite", "port", or "clone" Mike
- Mike source code appears in context and you are asked to implement from it
- You cannot confirm an implementation is independently designed
- A new dependency has an unclear or copyleft license

**Safe response:**
> "I'll implement this from requirements, not from Mike source. Let me write a clean
> requirement first."

See `.cursor/rules/agpl-cleanroom.mdc` for the full protocol.
This rule is an engineering IP-risk-control procedure, not legal advice.

---

## Retrieval system quick reference

Stack: FastAPI · PostgreSQL 16 + pgvector · Redis · MiniLM 384-d · cross-encoder rerank

```
docker compose up -d                          # Postgres :55432, Redis :6380
python scripts/ingest.py                      # load corpus
python scripts/embed.py                       # embed 41,788 chunks (~20 min CPU)
uvicorn app.api.main:app --reload             # API :8000, UI at /ui
pytest tests/                                 # 30 tests, must pass
python evals/retrieval_eval.py                # benchmark against 445 questions
```

Auth: `AUTH_ENABLED=false` (dev) trusts `X-Member-Id` header.
Set `AUTH_ENABLED=true` + issue keys with `python scripts/issue_keys.py` for production.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
