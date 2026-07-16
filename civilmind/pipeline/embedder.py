"""Embedding service — converts text chunks to vector embeddings.

Supports BGE (local sentence-transformers) and OpenCode Zen (API).
Wraps any embedder with CachedEmbedder for disk-based caching.
"""

from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np
import structlog

from civilmind.settings import settings

logger = structlog.get_logger()

CACHE_DIR = Path(os.path.expanduser("~")) / ".cache" / "civilmind" / "embeddings"


class BaseEmbedder(ABC):
    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    @property
    @abstractmethod
    def dimension(self) -> int: ...


class BGEEmbedder(BaseEmbedder):
    def __init__(self, model_name: str = "BAAI/bge-base-en-v1.5") -> None:
        self._model_name = model_name
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
            logger.info(
                "Loaded BGE model",
                model=self._model_name,
                dim=self._model.get_sentence_embedding_dimension(),
            )
        return self._model

    async def embed(self, text: str) -> list[float]:
        model = self._get_model()
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]

    @property
    def dimension(self) -> int:
        model = self._get_model()
        return model.get_sentence_embedding_dimension()


class OpenCodeEmbedder(BaseEmbedder):
    def __init__(self, model: str = "text-embedding-3-small") -> None:
        self._model = model
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=settings.LLM_API_KEY or "test-key",
                base_url=settings.LLM_BASE_URL or "https://opencode.ai/zen/v1",
            )
        return self._client

    async def embed(self, text: str) -> list[float]:
        client = self._get_client()
        resp = client.embeddings.create(model=self._model, input=text)
        return resp.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        client = self._get_client()
        responses: list[list[float]] = []
        batch_size = 2048
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = client.embeddings.create(model=self._model, input=batch)
            responses.extend(r.embedding for r in resp.data)
        return responses

    @property
    def dimension(self) -> int:
        return 1536


class CachedEmbedder(BaseEmbedder):
    """Wraps any embedder with disk-based caching."""

    def __init__(self, embedder: BaseEmbedder, cache_dir: Path = CACHE_DIR) -> None:
        self._embedder = embedder
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def _cache_path(self, text_hash: str) -> Path:
        return self._cache_dir / f"{text_hash}.npy"

    async def embed(self, text: str) -> list[float]:
        text_hash = self._hash(text.strip())
        cache_path = self._cache_path(text_hash)

        if cache_path.exists():
            vec = np.load(cache_path)
            return vec.tolist()

        vec = await self._embedder.embed(text)
        np.save(cache_path, np.array(vec))
        return vec

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        uncached: list[tuple[int, str]] = []
        results: list[list[float] | None] = [None] * len(texts)

        for i, text in enumerate(texts):
            text_hash = self._hash(text.strip())
            cache_path = self._cache_path(text_hash)
            if cache_path.exists():
                vec = np.load(cache_path)
                results[i] = vec.tolist()
            else:
                uncached.append((i, text))

        if uncached:
            uncached_texts = [t for _, t in uncached]
            computed = await self._embedder.embed_batch(uncached_texts)
            for (idx, text), vec in zip(uncached, computed):
                results[idx] = vec
                text_hash = self._hash(text.strip())
                np.save(self._cache_path(text_hash), np.array(vec))

        return [r for r in results if r is not None]

    @property
    def dimension(self) -> int:
        return self._embedder.dimension


class EmbedderFactory:
    @staticmethod
    def create(provider: str | None = None, use_cache: bool = True) -> BaseEmbedder:
        provider = provider or settings.EMBEDDING_PROVIDER
        model = settings.EMBEDDING_MODEL or ""

        if provider == "bge":
            embedder: BaseEmbedder = BGEEmbedder(model_name=model or "BAAI/bge-base-en-v1.5")
        elif provider in ("opencode", "openai", "custom"):
            embedder = OpenCodeEmbedder(model=model or "text-embedding-3-small")
        else:
            raise ValueError(f"Unknown embedding provider: {provider}")

        if use_cache:
            return CachedEmbedder(embedder)
        return embedder
