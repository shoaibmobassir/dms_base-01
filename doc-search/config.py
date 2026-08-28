from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://legal:legal@localhost:55432/legal_memory"
    docs_dir: str = "/Users/shoaibmobassir/Desktop/Experiments/Legal_Maal /DMS knowledge_base/docs"

    # ── LLM providers (tried in order: Groq → NVIDIA → Gemini → extractive) ──
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"

    nvidia_api_key: str = ""
    nvidia_model: str = "openai/gpt-oss-20b"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

    # ── retrieval ─────────────────────────────────────────────────────────────
    port: int = 8001
    embedding_dim: int = 384
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_ce_weight: float = 0.55
    retrieve_k: int = 8
    retrieve_limit: int = 40


settings = Settings()
