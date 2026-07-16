"""VisionLLMTool — image analysis via OpenCode Zen vision model.

Agents use this for architectural drawing analysis, layout understanding, etc.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx
import structlog

from civilmind.settings import settings
from civilmind.tools.base import BaseTool, ToolResult

logger = structlog.get_logger()

MAX_IMAGE_SIZE_MB = 20
DEFAULT_PROMPT = "Describe this architectural image in detail."


class VisionLLMTool(BaseTool):
    """Vision LLM analysis via OpenCode Zen (OpenAI-compatible)."""

    name = "vision_llm"
    description = "Analyze images using vision model"
    category = "vision"

    def __init__(self) -> None:
        self._api_key = settings.OPENCODE_API_KEY
        self._base_url = settings.OPENCODE_BASE_URL
        self._model = settings.VISION_MODEL

    async def execute(
        self,
        image_path: str,
        prompt: str = DEFAULT_PROMPT,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> ToolResult:
        """Analyze an image using the vision model.

        Args:
            image_path: Path to image file.
            prompt: Question or instruction about the image.
            max_tokens: Maximum tokens in the response.

        Returns:
            ToolResult with the model's analysis text.
        """
        path = Path(image_path)

        if not path.exists():
            return ToolResult(success=False, error=f"File not found: {image_path}")

        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > MAX_IMAGE_SIZE_MB:
            return ToolResult(
                success=False,
                error=f"Image too large: {size_mb:.1f}MB (max {MAX_IMAGE_SIZE_MB}MB)",
            )

        # Encode image as base64
        image_data = base64.b64encode(path.read_bytes()).decode("utf-8")
        suffix = path.suffix.lower().lstrip(".")
        mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}
        mime = f"image/{mime_map.get(suffix, 'jpeg')}"

        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{image_data}",
                            },
                        },
                    ],
                }
            ],
            "max_tokens": max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            text = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens")

            logger.info(
                "Vision analysis completed",
                model=self._model,
                tokens=tokens,
            )

            return ToolResult(
                success=True,
                data=text,
                tokens_used=tokens,
                metadata={"model": self._model, "file": str(path)},
            )

        except httpx.HTTPStatusError as e:
            logger.error("Vision API HTTP error", status=e.response.status_code)
            return ToolResult(
                success=False,
                error=f"API error {e.response.status_code}: {e.response.text[:200]}",
            )

        except Exception as e:
            logger.error("Vision analysis failed", error=str(e))
            return ToolResult(
                success=False,
                error=f"{type(e).__name__}: {e}",
            )
