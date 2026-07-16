"""OCRTool — text extraction from images via PaddleOCR.

Agents use this to extract text from scanned drawings, specs, and documents.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from civilmind.tools.base import BaseTool, ToolResult

logger = structlog.get_logger()

MAX_IMAGE_SIZE_MB = 20


class OCRTool(BaseTool):
    """PaddleOCR-based text extraction from images."""

    name = "ocr"
    description = "Extract text from images and scanned documents"
    category = "vision"

    def __init__(self) -> None:
        self._engine = None

    def _get_engine(self) -> Any:
        """Lazy-load PaddleOCR to avoid import-time cost."""
        if self._engine is None:
            from paddleocr import PaddleOCR

            self._engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        return self._engine

    async def execute(
        self,
        image_path: str,
        **kwargs: Any,
    ) -> ToolResult:
        """Extract text from an image file.

        Args:
            image_path: Path to image file (png, jpg, pdf, tiff).

        Returns:
            ToolResult with list of {text, confidence, bbox} dicts.
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

        try:
            engine = self._get_engine()
            result = engine.ocr(str(path), cls=True)

            if not result or not result[0]:
                return ToolResult(
                    success=True,
                    data=[],
                    metadata={"file": str(path), "size_mb": round(size_mb, 2)},
                )

            lines = []
            for line in result[0]:
                bbox, (text, confidence) = line
                lines.append(
                    {
                        "text": text,
                        "confidence": round(confidence, 4),
                        "bbox": bbox,
                    }
                )

            logger.info(
                "OCR completed",
                file=str(path),
                lines_extracted=len(lines),
            )

            return ToolResult(
                success=True,
                data=lines,
                metadata={"file": str(path), "size_mb": round(size_mb, 2)},
            )

        except Exception as e:
            logger.error("OCR failed", file=str(path), error=str(e))
            return ToolResult(
                success=False,
                error=f"{type(e).__name__}: {e}",
            )
