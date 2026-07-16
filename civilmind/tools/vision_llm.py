"""VisionLLMTool — image analysis via vision LLM.

Agents use this for architectural drawing analysis, layout understanding, etc.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import structlog

from civilmind.llm import LLMClient
from civilmind.settings import settings
from civilmind.tools.base import BaseTool, ToolResult

logger = structlog.get_logger()


class VisionLLMTool(BaseTool):
    """Vision LLM analysis via configured provider."""

    name = "vision_llm"
    description = "Analyze images using vision model"
    category = "vision"

    def __init__(self) -> None:
        self._client = LLMClient(settings.llm_vision_config)
        self._max_image_size_mb = settings.VISION_MAX_IMAGE_SIZE_MB
        self._default_prompt = settings.VISION_DEFAULT_PROMPT

    async def execute(
        self,
        image_path: str,
        prompt: str | None = None,
        max_tokens: int | None = None,
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
        if size_mb > self._max_image_size_mb:
            return ToolResult(
                success=False,
                error=f"Image too large: {size_mb:.1f}MB (max {self._max_image_size_mb}MB)",
            )

        image_data = base64.b64encode(path.read_bytes()).decode("utf-8")
        suffix = path.suffix.lower().lstrip(".")
        mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}
        mime = f"image/{mime_map.get(suffix, 'jpeg')}"

        try:
            result = await self._client.vision(
                image_data=image_data,
                mime_type=mime,
                prompt=prompt or self._default_prompt,
                max_tokens=max_tokens,
            )

            logger.info(
                "Vision analysis completed",
                model=result.model,
                tokens=result.tokens_used,
            )

            return ToolResult(
                success=True,
                data=result.content,
                tokens_used=result.tokens_used,
                metadata={"model": result.model, "file": str(path)},
            )

        except Exception as e:
            logger.error("Vision analysis failed", error=str(e))
            return ToolResult(
                success=False,
                error=f"{type(e).__name__}: {e}",
            )
