"""LLM client — provider-agnostic wrapper for chat + vision.

Supports any OpenAI-compatible API (OpenCode Zen, OpenAI, Anthropic,
Groq, Together, etc.) plus native Anthropic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

import httpx
import structlog

logger = structlog.get_logger()


class LLMProvider(StrEnum):
    OPENCODE_ZEN = "opencode"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    CUSTOM = "custom"  # any OpenAI-compatible endpoint


@dataclass
class LLMConfig:
    """Configuration for an LLM provider.

    For OpenAI-compatible providers, only api_key + base_url + model are needed.
    For Anthropic native, set provider=anthropic and provide api_key + model.
    """

    provider: LLMProvider = LLMProvider.OPENCODE_ZEN
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout_seconds: int = 60

    # Provider-specific overrides (set by settings)
    anthropic_api_url: str = "https://api.anthropic.com/v1/messages"
    anthropic_version: str = "2023-06-01"

    # Optional overrides per call
    extra_headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class LLMResult:
    content: str
    model: str
    tokens_used: int | None = None
    finish_reason: str | None = None


class LLMClient:
    """Provider-agnostic LLM client for chat and vision."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._http = httpx.AsyncClient(timeout=config.timeout_seconds)

    async def chat(
        self,
        messages: list[LLMMessage],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        """Simple text chat. Supports OpenAI-compatible and Anthropic."""
        if self._config.provider in (
            LLMProvider.OPENCODE_ZEN,
            LLMProvider.OPENAI,
            LLMProvider.CUSTOM,
        ):
            return await self._chat_openai(messages, system_prompt, max_tokens, temperature)
        if self._config.provider == LLMProvider.ANTHROPIC:
            return await self._chat_anthropic(messages, system_prompt, max_tokens, temperature)
        raise ValueError(f"Unsupported provider: {self._config.provider}")

    async def vision(
        self,
        image_data: str,  # base64-encoded
        mime_type: str,
        prompt: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        """Vision analysis. Supports OpenAI-compatible and Anthropic."""
        if self._config.provider in (
            LLMProvider.OPENCODE_ZEN,
            LLMProvider.OPENAI,
            LLMProvider.CUSTOM,
        ):
            return await self._vision_openai(image_data, mime_type, prompt, max_tokens, temperature)
        if self._config.provider == LLMProvider.ANTHROPIC:
            return await self._vision_anthropic(
                image_data, mime_type, prompt, max_tokens, temperature
            )
        raise ValueError(f"Unsupported provider for vision: {self._config.provider}")

    async def _chat_openai(
        self,
        messages: list[LLMMessage],
        system_prompt: str | None,
        max_tokens: int | None,
        temperature: float | None,
    ) -> LLMResult:
        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": [
                *([{"role": "system", "content": system_prompt}] if system_prompt else []),
                *[{"role": m.role, "content": m.content} for m in messages],
            ],
            "max_tokens": max_tokens or self._config.max_tokens,
            "temperature": temperature if temperature is not None else self._config.temperature,
        }
        body.update(self._config.extra_body)

        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
            **self._config.extra_headers,
        }

        try:
            resp = await self._http.post(
                f"{self._config.base_url}/chat/completions",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            return LLMResult(
                content=choice["message"]["content"],
                model=data.get("model", self._config.model),
                tokens_used=data.get("usage", {}).get("total_tokens"),
                finish_reason=choice.get("finish_reason"),
            )
        except httpx.HTTPStatusError as e:
            logger.error("LLM API error", status=e.response.status_code, body=e.response.text[:300])
            raise

    async def _vision_openai(
        self,
        image_data: str,
        mime_type: str,
        prompt: str,
        max_tokens: int | None,
        temperature: float | None,
    ) -> LLMResult:
        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_data}",
                            },
                        },
                    ],
                }
            ],
            "max_tokens": max_tokens or self._config.max_tokens,
            "temperature": temperature if temperature is not None else self._config.temperature,
        }
        body.update(self._config.extra_body)

        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
            **self._config.extra_headers,
        }

        try:
            resp = await self._http.post(
                f"{self._config.base_url}/chat/completions",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            return LLMResult(
                content=choice["message"]["content"],
                model=data.get("model", self._config.model),
                tokens_used=data.get("usage", {}).get("total_tokens"),
                finish_reason=choice.get("finish_reason"),
            )
        except httpx.HTTPStatusError as e:
            logger.error(
                "Vision API error", status=e.response.status_code, body=e.response.text[:300]
            )
            raise

    async def _chat_anthropic(
        self,
        messages: list[LLMMessage],
        system_prompt: str | None,
        max_tokens: int | None,
        temperature: float | None,
    ) -> LLMResult:
        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens or self._config.max_tokens,
            "temperature": temperature if temperature is not None else self._config.temperature,
        }
        if system_prompt:
            body["system"] = system_prompt

        headers = {
            "x-api-key": self._config.api_key,
            "anthropic-version": self._config.anthropic_version,
            "Content-Type": "application/json",
            **self._config.extra_headers,
        }

        try:
            resp = await self._http.post(
                self._config.anthropic_api_url,
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            return LLMResult(
                content=data["content"][0]["text"],
                model=data.get("model", self._config.model),
                tokens_used=data.get("usage", {}).get("input_tokens", 0)
                + data.get("usage", {}).get("output_tokens", 0),
                finish_reason=data["content"][0].get("stop_reason"),
            )
        except httpx.HTTPStatusError as e:
            logger.error(
                "Anthropic API error", status=e.response.status_code, body=e.response.text[:300]
            )
            raise

    async def _vision_anthropic(
        self,
        image_data: str,
        mime_type: str,
        prompt: str,
        max_tokens: int | None,
        temperature: float | None,
    ) -> LLMResult:
        media_type = mime_type
        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "max_tokens": max_tokens or self._config.max_tokens,
            "temperature": temperature if temperature is not None else self._config.temperature,
        }

        headers = {
            "x-api-key": self._config.api_key,
            "anthropic-version": self._config.anthropic_version,
            "Content-Type": "application/json",
            **self._config.extra_headers,
        }

        try:
            resp = await self._http.post(
                self._config.anthropic_api_url,
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            return LLMResult(
                content=data["content"][0]["text"],
                model=data.get("model", self._config.model),
                tokens_used=data.get("usage", {}).get("input_tokens", 0)
                + data.get("usage", {}).get("output_tokens", 0),
                finish_reason=data["content"][0].get("stop_reason"),
            )
        except httpx.HTTPStatusError as e:
            logger.error(
                "Anthropic vision error", status=e.response.status_code, body=e.response.text[:300]
            )
            raise

    async def close(self) -> None:
        await self._http.aclose()
