"""Pydantic settings — deployment facts loaded from .env.

Secrets have no defaults — the app refuses to start if they're missing.
This catches misconfiguration at boot, not on first user request.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from civilmind.llm.client import LLMConfig, LLMProvider


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    APP_NAME: str = Field(default="CivilMind AI")
    DEBUG: bool = Field(default=False)
    SECRET_KEY: str = Field(default="")

    # ============================================================
    # PostgreSQL
    # ============================================================
    POSTGRES_HOST: str = Field(default="localhost")
    POSTGRES_PORT: int = Field(default=5432)
    POSTGRES_USER: str = Field(default="civilmind")
    POSTGRES_PASSWORD: str = Field(default="civilmind")
    POSTGRES_DB: str = Field(default="civilmind")

    @property
    def DATABASE_URL(self) -> str:  # noqa: N802
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:  # noqa: N802
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ============================================================
    # Qdrant
    # ============================================================
    QDRANT_HOST: str = Field(default="localhost")
    QDRANT_PORT: int = Field(default=6333)
    QDRANT_COLLECTION: str = Field(default="civilmind")

    @property
    def QDRANT_URL(self) -> str:  # noqa: N802
        return f"http://{self.QDRANT_HOST}:{self.QDRANT_PORT}"

    # ============================================================
    # MinIO
    # ============================================================
    MINIO_ENDPOINT: str = Field(default="localhost:9000")
    MINIO_ACCESS_KEY: str = Field(default="minioadmin")
    MINIO_SECRET_KEY: str = Field(default="minioadmin")
    MINIO_BUCKET: str = Field(default="civilmind-docs")
    MINIO_SECURE: bool = Field(default=False)

    # ============================================================
    # Neo4j
    # ============================================================
    NEO4J_URI: str = Field(default="bolt://localhost:7687")
    NEO4J_USER: str = Field(default="neo4j")
    NEO4J_PASSWORD: str = Field(default="password")

    # ============================================================
    # Redis
    # ============================================================
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # ============================================================
    # LLM — provider-agnostic
    # ============================================================
    LLM_PROVIDER: Literal["opencode", "openai", "anthropic", "custom"] = Field(default="opencode")
    LLM_API_KEY: str = Field(default="")
    LLM_BASE_URL: str = Field(default="")
    LLM_CHAT_MODEL: str = Field(default="")
    LLM_VISION_MODEL: str = Field(default="")

    # Anthropic-specific
    ANTHROPIC_API_URL: str = Field(default="https://api.anthropic.com/v1/messages")
    ANTHROPIC_VERSION: str = Field(default="2023-06-01")

    # LLM defaults
    LLM_MAX_TOKENS: int = Field(default=4096)
    LLM_TEMPERATURE: float = Field(default=0.7)
    LLM_TIMEOUT_SECONDS: int = Field(default=60)

    # ============================================================
    # Embeddings
    # ============================================================
    EMBEDDING_PROVIDER: str = Field(default="bge")
    EMBEDDING_MODEL: str = Field(default="")

    # ============================================================
    # Vision tool
    # ============================================================
    VISION_MAX_IMAGE_SIZE_MB: int = Field(default=20)
    VISION_DEFAULT_PROMPT: str = Field(default="Describe this architectural image in detail.")

    # ============================================================
    # OCR tool
    # ============================================================
    OCR_MAX_IMAGE_SIZE_MB: int = Field(default=20)

    # ============================================================
    # SQL Query tool
    # ============================================================
    SQL_QUERY_TIMEOUT_SECONDS: int = Field(default=5)
    SQL_QUERY_MAX_ROWS: int = Field(default=1000)

    # ============================================================
    # Document config
    # ============================================================
    SUPPORTED_DOC_FORMATS: str = Field(default=".pdf,.docx,.xlsx,.png,.jpg,.jpeg")

    # ============================================================
    # OCR / Document Parsing
    # ============================================================
    PADDLEOCR_ENABLED: bool = Field(default=True)
    TESSERACT_LANG: str = Field(default="eng")

    # ============================================================
    # Embedding dimensions (comma-separated key=val pairs)
    # ============================================================
    EMBEDDING_DIMS_CSV: str = Field(default="BAAI/bge-base-en-v1.5=768,BAAI/bge-small-en-v1.5=384")

    @property
    def SUPPORTED_FORMATS(self) -> dict[str, str]:  # noqa: N802
        fmt_map = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }
        parts = [s.strip() for s in self.SUPPORTED_DOC_FORMATS.split(",") if s.strip()]
        return {ext: fmt_map[ext] for ext in parts if ext in fmt_map}

    @property
    def EMBEDDING_DIMS(self) -> dict[str, int]:  # noqa: N802
        dims = {}
        for pair in self.EMBEDDING_DIMS_CSV.split(","):
            pair = pair.strip()
            if "=" in pair:
                key, val = pair.split("=", 1)
                dims[key.strip()] = int(val.strip())
        return dims

    @property
    def llm_chat_config(self) -> LLMConfig:
        return self._build_llm_config(self.LLM_CHAT_MODEL)

    @property
    def llm_vision_config(self) -> LLMConfig:
        return self._build_llm_config(self.LLM_VISION_MODEL)

    def _build_llm_config(self, model: str) -> LLMConfig:
        provider_map = {
            "opencode": LLMProvider.OPENCODE_ZEN,
            "openai": LLMProvider.OPENAI,
            "anthropic": LLMProvider.ANTHROPIC,
            "custom": LLMProvider.CUSTOM,
        }

        return LLMConfig(
            provider=provider_map[self.LLM_PROVIDER],
            api_key=self.LLM_API_KEY,
            base_url=self.LLM_BASE_URL,
            model=model,
            max_tokens=self.LLM_MAX_TOKENS,
            temperature=self.LLM_TEMPERATURE,
            timeout_seconds=self.LLM_TIMEOUT_SECONDS,
            anthropic_api_url=self.ANTHROPIC_API_URL,
            anthropic_version=self.ANTHROPIC_VERSION,
        )


settings = Settings()
