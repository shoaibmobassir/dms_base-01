from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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


settings = Settings()
