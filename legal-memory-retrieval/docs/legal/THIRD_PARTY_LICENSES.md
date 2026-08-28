# Third-Party License Summary

Summary of licenses used by production dependencies. Full license texts are
available via each package's PyPI page or source repository.

**Last updated:** 2026-08-27

---

| License | Packages |
|---------|---------|
| MIT | fastapi, pgvector, python-dotenv, redis, python-jose, passlib |
| BSD-3-Clause | uvicorn, httpx, passlib |
| Apache-2.0 | sentence-transformers, opentelemetry-sdk, opentelemetry-instrumentation-fastapi, prometheus-client, pytest-asyncio |
| LGPL-3.0 | psycopg[binary] — used as a dynamically-linked library; our code is not a derivative work of psycopg |
| MIT + PostgreSQL License | pgvector/pgvector Docker image |
| BSD-3-Clause | redis:7-alpine Docker image |

---

## LGPL note (psycopg)

`psycopg` is LGPL-3.0. LGPL permits use in proprietary software when the LGPL
library is dynamically linked (not statically incorporated). We use the binary
wheel which is dynamically linked. We do not modify psycopg source. This usage
is standard for proprietary Python applications. Confirm with counsel if
distribution method changes (e.g. static compilation or bundling).

---

## Packages NOT used (and why noted)

| Package | License | Reason not used |
|---------|---------|----------------|
| Mike (the project) | AGPLv3 | AGPL copyleft with network-use obligations. Used as product research only. Zero source code imported. |
| langchain | MIT (core) but ecosystem varies | Not used — own pipeline built |
| llama-index | MIT | Not used — own pipeline built |

---

## Adding new dependencies

See `DEPENDENCY_AUDIT.md` for the audit protocol and approval workflow.
