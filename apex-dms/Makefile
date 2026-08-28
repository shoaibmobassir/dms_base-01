.PHONY: run build test dev infra infra-down migrate lint

# --- Development ---

# Run the server with hot-reload (air)
dev:
	go run ./cmd/server

# Build the binary
build:
	go build -o bin/apex-dms ./cmd/server

# Run the binary
run: build
	./bin/apex-dms

# Run tests
test:
	go test -v -race ./...

# Lint
lint:
	golangci-lint run ./...

# --- Infrastructure ---

# Start Postgres + Redis + MinIO
infra:
	docker compose up -d

# Stop infrastructure
infra-down:
	docker compose down

# --- Database ---

# Run migrations (via the server startup, or manually)
migrate:
	go run ./cmd/server --migrate-only

# Create a new migration
migration:
	@read -p "Migration name: " name; \
	goose -dir internal/db/migrations create $$name sql

# --- Utilities ---

# Generate a JWT secret
secret:
	openssl rand -hex 64

# Copy .env.example to .env
env:
	cp -n .env.example .env || true
