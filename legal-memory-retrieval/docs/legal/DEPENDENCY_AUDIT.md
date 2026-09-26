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

---

## Frontend npm dependencies (`frontend/package.json`)

Added 2026-09-22 for FirmOS Vite SPA. No AGPL/GPL/SSPL packages.

| Package | License (typical) | Copyleft? | Approved |
|---------|-------------------|-----------|----------|
| react / react-dom | MIT | No | ✅ |
| react-router-dom | MIT | No | ✅ |
| @tanstack/react-query | MIT | No | ✅ |
| @radix-ui/react-* (dialog, dropdown-menu, scroll-area, separator, slot, tabs, tooltip) | MIT | No | ✅ |
| class-variance-authority | Apache-2.0 | No | ✅ |
| clsx / tailwind-merge | MIT | No | ✅ |
| cmdk | MIT | No | ✅ |
| lucide-react | ISC | No | ✅ |
| sonner | MIT | No | ✅ |
| tailwindcss-animate | MIT | No | ✅ |
| vite / @vitejs/plugin-react | MIT | No | ✅ |
| typescript | Apache-2.0 | No | ✅ |
| tailwindcss / postcss / autoprefixer | MIT | No | ✅ |

**Not included (intentionally):** Emergent overlay packages, PostHog, CRA/CRACO, axios.


### Added 2026-09-24 (production plan 06)

| Package | License | Copyleft? | Scope | Approved |
|---------|---------|-----------|-------|----------|
| @playwright/test 1.63.0 | Apache-2.0 | No | devDependency (browser tests only; not shipped) | ✅ |

### Added 2026-09-25 (chat workspace viewer)

| Package | License | Copyleft? | Scope | Approved |
|---------|---------|-----------|-------|----------|
| pdfjs-dist 6.x | Apache-2.0 | No | Frontend runtime (PDF page rendering + text layer for highlights) | ✅ |
| pdf.js runtime assets (`wasm/`, `standard_fonts/`, `cmaps/`, `iccs/` from pdfjs-dist) | Apache-2.0 (pdf.js), BSD-2 (OpenJPEG), BSD-3 (PDFium JBIG2), MIT (qcms); fonts under their bundled licences | No | Frontend runtime; copied to `public/pdfjs/` by `scripts/copy-pdfjs-assets.mjs` (decodes scanned-page images) | ✅ |
| Tesseract OCR (system binary) | Apache-2.0 | No | Separate process: ingest OCR (existing) and `app/documents/page_words.py` word boxes for highlights on scanned pages | ✅ |
| Poppler `pdftoppm` (system binary) | GPL-2.0/3.0 | Yes (strong) | Not bundled or linked; invoked as a separate process by ingest OCR (existing) and `page_words.py`. Was already in use but unrecorded | ⏳ Pending owner approval (GPL tool, process boundary only) |
| LibreOffice (system binary, optional) | MPL-2.0 | Weak (file-level) | Not bundled or linked; invoked as a separate process by `app/documents/pdf_render.py` only if installed on the server | ⏳ Pending owner approval — code works without it (Word files fall back to the text view) |
