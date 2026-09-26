# Local workflow. Paths contain spaces upstream, so every recipe runs from here.
PY ?= .venv/bin/python

.PHONY: up migrate seed seed-reset api web build test test-api test-e2e test-e2e-llm check

up:            ## Postgres :55432 + Redis :6380
	docker compose up -d

migrate:       ## apply app/db/migrations/*.sql (idempotent)
	$(PY) scripts/migrate.py

seed: migrate  ## deterministic demo data on top of the ingested corpus
	$(PY) scripts/seed_demo.py
	$(PY) scripts/seed_acme.py

seed-reset:    ## remove seeded rows and lift the demo ethical walls
	$(PY) scripts/seed_demo.py --reset

api:           ## API + built SPA on :8000 (/ui)
	$(PY) -m uvicorn app.api.main:app --reload --port 8000

web:           ## Vite dev server on :5173/ui, proxying /api to :8000
	cd frontend && npm run dev

build:         ## type-check and build the SPA into static/
	cd frontend && npm run build

test-api:      ## backend suite, including DB-backed contract + security tests
	$(PY) -m pytest tests -q

test-e2e: build ## browser tests against the seeded DB (uses installed Chrome)
	cd frontend && npm run test:e2e

test-e2e-llm: build ## also exercise chat through the configured LLM
	cd frontend && E2E_LLM=1 npm run test:e2e

test: test-api test-e2e

check: seed test  ## everything, from a running `make up`
