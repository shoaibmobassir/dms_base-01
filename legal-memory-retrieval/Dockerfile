# API + built SPA in one image. Build from this directory:
#   docker build -t firmos-api .
# Run with the compose "app" profile (see docker-compose.yml), which supplies the
# production environment. The container refuses to start with unsafe settings.

# ── 1. Build the SPA into /static ──────────────────────────────────────────────
FROM node:22-alpine AS spa
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci
COPY frontend/ ./
# vite writes to ../static (see vite.config.ts)
RUN mkdir -p ../static && npm run build

# ── 2. Python runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/models \
    ENV=production

WORKDIR /app
COPY requirements.lock ./
# Locked, hash-checked dependencies (regenerate: see docs/runbooks/release.md).
# CPU-only torch keeps the image ~1.5 GB smaller than the CUDA build.
RUN pip install --require-hashes --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.lock

# Bake the embedding and rerank models in so the first request doesn't download them.
ARG RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); CrossEncoder('${RERANK_MODEL}')"

COPY app ./app
COPY scripts ./scripts
COPY docs/ARCHITECTURE.md ./docs/ARCHITECTURE.md
COPY --from=spa /src/static ./static

RUN useradd --system --uid 10001 --home /app firmos \
 && mkdir -p /app/data/object_store && chown -R firmos /app/data /opt/models
USER firmos

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/system/ready', timeout=4).status == 200 else 1)"

# Migrations are idempotent; apply them before serving.
CMD ["sh", "-c", "python scripts/migrate.py && exec uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2} --proxy-headers"]
