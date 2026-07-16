"""Pydantic settings — deployment facts loaded from .env.

Secrets have no defaults — the app refuses to start if they're missing.
This catches misconfiguration at boot, not on first user request.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    APP_NAME: str = "CivilMind AI"
    DEBUG: bool = False

    # PostgreSQL
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "civilmind"
    POSTGRES_PASSWORD: str = "civilmind"
    POSTGRES_DB: str = "civilmind"

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

    # Qdrant
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION: str = "civilmind"

    @property
    def QDRANT_URL(self) -> str:  # noqa: N802
        return f"http://{self.QDRANT_HOST}:{self.QDRANT_PORT}"

    # MinIO
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "civilmind-docs"

    # Neo4j
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # OpenCode Zen — single key for all LLM calls (OpenAI-compatible)
    OPENCODE_API_KEY: str = Field(..., description="Required. Get from https://opencode.ai/zen")
    OPENCODE_BASE_URL: str = "https://opencode.ai/zen/v1"

    # LLM models via OpenCode Zen
    LLM_MODEL: str = Field(
        ..., description="Required. e.g. opencode/claude-sonnet-4-5, opencode/gpt-5"
    )
    VISION_MODEL: str = Field(
        ..., description="Required. e.g. opencode/gpt-5, opencode/claude-sonnet-4-5"
    )
    EMBEDDING_PROVIDER: str = "bge"  # bge | opencode
    EMBEDDING_MODEL: str = Field(
        ..., description="Required. Must exist in config.py EMBEDDING_DIMS lookup."
    )


settings = Settings()
