import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Secrets may be files named after the setting (e.g. /run/secrets/precentis/oidc_client_secret),
# as mounted by ECS, Kubernetes or Container Apps from a secrets manager. Environment
# variables still win; files avoid putting secrets in the environment or the image.
_SECRETS_DIR = os.environ.get("SECRETS_DIR")

# The knowledge-base workspace (parent of this project): corpus, docs/, manifests.
_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        secrets_dir=_SECRETS_DIR if _SECRETS_DIR and Path(_SECRETS_DIR).is_dir() else None,
    )

    # ── Deployment ───────────────────────────────────────────────────────
    env: str = "development"  # development | production
    # false trusts the X-Member-Id header (dev only); true requires X-Api-Key.
    auth_enabled: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Server directories bulk ingest jobs may read (comma list). Empty = the
    # knowledge-base workspace; set explicitly in production.
    ingest_allowed_roots: str = ""
    # ── Firm sign-in (OIDC, authorization code + PKCE) ────────────────────
    oidc_issuer: str = ""  # e.g. https://login.microsoftonline.com/<tenant>/v2.0
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""  # https://<host>/api/auth/callback
    oidc_scopes: str = "openid email profile"
    # Browser sessions: absolute lifetime and idle timeout.
    session_ttl_hours: int = 12
    session_idle_minutes: int = 60
    session_cookie_secure: bool = True  # False only for http://localhost development
    # Lawyers sign in with OIDC; pasting an API key into the SPA is a development aid.
    allow_api_key_browser_login: bool = True

    # ── Uploads (enforced while the request streams in) ──────────────────
    max_upload_file_mb: int = 100
    max_upload_batch_mb: int = 1024
    max_upload_files: int = 500
    # inline: process upload batches inside the request (development, tests)
    # queue:  the API only enqueues; `python -m app.workers.ingest` processes them
    ingest_mode: str = "inline"
    ingest_stale_minutes: int = 30  # a running batch with no heartbeat this long is reclaimed
    # off | clamd  (ClamAV daemon over TCP; GPL service — needs legal sign-off to enable)
    malware_scanner: str = "off"
    clamd_host: str = "localhost"
    clamd_port: int = 3310

    # Projects/activity APIs have no UI since the frontend prune; off unless needed.
    enable_legacy_projects: bool = False

    database_url: str = "postgresql://legal:legal@localhost:55432/legal_memory"
    corpus_dir: str = "../dummy-firm/data"
    embedding_dim: int = 384
    index_version: str = "corpus-v2-frozen"
    retrieve_k: int = 20
    retrieval_channels: str = "keyword,metadata,vector,graph"
    rerank_enabled: bool = True
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_candidates: int = 100
    rerank_ce_weight: float = 0.55
    groq_api_key: str = ""
    gemini_api_key: str = ""
    answer_provider: str = "auto"
    groq_model: str = "llama3-70b-8192"
    gemini_model: str = "gemini-1.5-flash"
    # Amazon Bedrock (bearer token — set AWS_BEARER_TOKEN_BEDROCK)
    aws_bearer_token_bedrock: str = ""
    bedrock_region: str = "us-east-1"
    # Embeddings often need a different Runtime region (Mantle chat stays on bedrock_region).
    bedrock_embedding_region: str = "us-east-2"
    bedrock_model: str = "zai.glm-5"
    bedrock_embedding_model: str = "amazon.titan-embed-text-v2:0"
    # Titan v2 accepts 256/512/1024. Do NOT point production retrieval at Bedrock
    # embeddings without a schema + full re-embed (corpus is MiniLM 384-d).
    bedrock_embedding_dimensions: int = 1024
    embedding_provider: str = "minilm"  # minilm | bedrock
    redis_url: str = "redis://localhost:6380"
    cache_ttl_seconds: int = 300

    # ── Object storage (FirmOS Phase 3) ───────────────────────────────────
    tenant_id: str = "harbour"
    object_store_backend: str = "local"  # local | s3
    object_store_root: str = "./data/object_store"
    object_store_bucket: str = "firmos"
    object_store_endpoint: str = "http://localhost:9000"
    object_store_access_key: str = "minioadmin"
    object_store_secret_key: str = "minioadmin"
    object_store_region: str = "us-east-1"

    # ── Async connection pool ────────────────────────────────────────────
    db_pool_min_size: int = 4
    db_pool_max_size: int = 20
    db_pool_max_idle: float = 300.0

    # ── Version-based cache invalidation ─────────────────────────────────
    knowledge_version: int = 1
    permission_version: int = 1
    embedding_version: str = "minilm-l6-v2"

    # ── Retrieval engine v2 ──────────────────────────────────────────────
    use_engine_v2: bool = True

    # ── Chat agent bounds ────────────────────────────────────────────────
    # Last N user/assistant pairs kept in the LLM prompt (empty assistants dropped).
    chat_history_max_pairs: int = 10
    chat_tool_timeout_seconds: float = 30.0
    chat_find_timeout_seconds: float = 10.0
    # In-process rate limits for LLM endpoints (per member / anonymous key).
    rate_limit_ask_per_minute: int = 30
    rate_limit_chat_per_minute: int = 20

    # ── Universal source sync (Phase 0) ───────────────────────────────────
    sources_sync_enabled: bool = False
    sources_token_encryption_secret: str = (
        "firmos-dev-sources-token-encryption-secret-32b"
    )
    sources_queue_inline: bool = True  # process jobs in-process when True
    sources_sync_max_retries: int = 5
    sources_sync_backoff_base_seconds: float = 1.0

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_client_id and self.oidc_redirect_uri)

    @property
    def ingest_root_list(self) -> list[Path]:
        roots = [r.strip() for r in self.ingest_allowed_roots.split(",") if r.strip()]
        return [Path(r).resolve() for r in roots] or [_WORKSPACE_ROOT]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def production_problems(self) -> list[str]:
        """Settings that are unsafe outside local development."""
        problems = []
        if not self.auth_enabled:
            problems.append("AUTH_ENABLED must be true (false trusts a client-supplied member header)")
        if "*" in self.cors_origin_list:
            problems.append("CORS_ORIGINS must list explicit origins, not '*'")
        if self.sources_token_encryption_secret == Settings.model_fields["sources_token_encryption_secret"].default:
            problems.append("SOURCES_TOKEN_ENCRYPTION_SECRET is the development default")
        if self.object_store_backend == "s3" and self.object_store_secret_key == "minioadmin":
            problems.append("OBJECT_STORE_SECRET_KEY is the development default")
        if not self.ingest_allowed_roots.strip():
            problems.append("INGEST_ALLOWED_ROOTS must be set explicitly")
        if "legal:legal@" in self.database_url:
            problems.append("DATABASE_URL uses the development credentials")
        if not self.oidc_enabled:
            problems.append("OIDC_ISSUER / OIDC_CLIENT_ID / OIDC_REDIRECT_URI must be set (firm sign-in)")
        if self.allow_api_key_browser_login:
            problems.append("ALLOW_API_KEY_BROWSER_LOGIN must be false (API keys are for service callers)")
        if not self.session_cookie_secure:
            problems.append("SESSION_COOKIE_SECURE must be true")
        if self.ingest_mode != "queue":
            problems.append("INGEST_MODE must be 'queue' (parsing and embedding off the API process)")
        if self.malware_scanner == "off":
            problems.append("MALWARE_SCANNER is off (uploads would be ingested unscanned)")
        return problems


settings = Settings()
