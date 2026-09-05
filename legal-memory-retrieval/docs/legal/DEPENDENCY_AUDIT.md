# Dependency Audit

All production and dev dependencies must be recorded here before being added.
Update the Approved column when a human owner reviews an uncertain license.

**Approver:** project owner  
**Last reviewed:** 2026-08-27

---

## Production dependencies (`requirements.txt`)

| Package | Version | License | Copyleft? | Network obligations? | Commercial use | Approved |
|---------|---------|---------|-----------|---------------------|---------------|----------|
| fastapi | >=0.115.0 | MIT | No | No | Yes | ✅ |
| uvicorn | >=0.32.0 | BSD-3-Clause | No | No | Yes | ✅ |
| psycopg[binary] | >=3.2.0 | LGPL-3.0 | Weak (LGPL) | No | Yes — dynamic link | ✅ |
| pydantic-settings | >=2.6.0 | MIT | No | No | Yes | ✅ |
| sentence-transformers | >=3.0.0 | Apache-2.0 | No | No | Yes | ✅ |
| pgvector | >=0.3.6 | MIT | No | No | Yes | ✅ |
| python-dotenv | >=1.0.0 | BSD-3-Clause | No | No | Yes | ✅ |
| httpx | >=0.27.0 | BSD-3-Clause | No | No | Yes | ✅ |
| redis | >=4.0.0 | MIT | No | No | Yes | ✅ |
| opentelemetry-sdk | >=1.20.0 | Apache-2.0 | No | No | Yes | ✅ |
| opentelemetry-instrumentation-fastapi | >=0.40b0 | Apache-2.0 | No | No | Yes | ✅ |
| prometheus-client | >=0.17.0 | Apache-2.0 | No | No | Yes | ✅ |
| python-jose | >=3.3.0 | MIT | No | No | Yes | ✅ |
| passlib | >=1.7.4 | BSD-3-Clause | No | No | Yes | ✅ |
| pypdf | >=5.0.0 | BSD-3-Clause | No | No | Yes | ✅ |
| python-docx | >=1.1.0 | MIT | No | No | Yes | ✅ |
| PyYAML | >=6.0.0 | MIT | No | No | Yes | ✅ |
| python-multipart | >=0.0.9 | Apache-2.0 | No | No | Yes | ✅ |

**Transitive dependencies of note:**

| Package | License | Note |
|---------|---------|------|
| torch (via sentence-transformers) | BSD-3-Clause | No copyleft |
| transformers (via sentence-transformers) | Apache-2.0 | No copyleft |
| numpy | BSD-3-Clause | No copyleft |
| cryptography (via python-jose) | Apache-2.0 + BSD | No copyleft |

---

## Dev dependencies (`requirements-dev.txt`)

| Package | Version | License | Approved |
|---------|---------|---------|----------|
| pytest | >=8.0.0 | MIT | ✅ |
| pytest-asyncio | >=0.23.0 | Apache-2.0 | ✅ |

---

## Infrastructure (docker-compose.yml)

| Image | License | Note |
|-------|---------|------|
| pgvector/pgvector:pg16 | MIT (pgvector) + PostgreSQL License | ✅ Both permissive |
| redis:7-alpine | BSD-3-Clause | ✅ |

---

## Review protocol for new dependencies

Before adding any package:

1. Check license on PyPI (`pip show <pkg>`) or npm
2. Add a row to this table
3. If License column contains AGPL / GPL / LGPL / SSPL / Elastic / BSL / Commons Clause → mark Approved as `⏳ PENDING` and get human sign-off before merging
4. If unclear → mark `❓ REVIEW` and escalate

## AGPL / GPL flag

Any package under AGPL or GPL **must not be added to production dependencies** without explicit legal review, because their copyleft could extend to our proprietary code distributed over a network.
