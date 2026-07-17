"""OCR engine — extracts text from images and scanned PDFs.

Uses PaddleOCR for text extraction from construction documents.
Wraps sync PaddleOCR in async interface.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

MAX_IMAGE_SIZE_MB = 10


@dataclass
class OCRResult:
    """Single OCR extraction result."""

    text: str
    confidence: float
    bbox: list[list[int]] = field(default_factory=list)
    page: int | None = None


class OCREngine:
    """PaddleOCR wrapper for text extraction from construction documents.

    Extracts text from images, scanned PDFs, and floor plans.
    Handles rotation, skew, and noisy backgrounds.
    """

    def __init__(self, lang: str = "en") -> None:
        self._lang = lang
        self._engine: Any | None = None

    def _get_engine(self) -> Any:
        """Lazy-load PaddleOCR engine."""
        if self._engine is None:
            try:
                from paddleocr import PaddleOCR

                self._engine = PaddleOCR(use_angle_cls=True, lang=self._lang)
                logger.info("PaddleOCR initialized", lang=self._lang)
            except ImportError:
                logger.error("PaddleOCR not installed", hint="pip install paddleocr paddlepaddle")
                raise
        return self._engine

    def _extract_sync(self, image_path: str) -> list[OCRResult]:
        """Synchronous OCR extraction."""
        engine = self._get_engine()
        result = engine.ocr(image_path, cls=True)

        results: list[OCRResult] = []
        if not result or not result[0]:
            return results

        for line in result[0]:
            bbox = [[int(p[0]), int(p[1])] for p in line[0]]
            text = line[1][0]
            confidence = float(line[1][1])
            results.append(OCRResult(text=text, confidence=confidence, bbox=bbox))

        return results

    async def extract_text(self, image_path: str) -> list[OCRResult]:
        """Extract text from image or PDF.

        Args:
            image_path: Path to image or PDF file.

        Returns:
            List of OCRResult with extracted text and positions.

        Raises:
            FileNotFoundError: If file doesn't exist.
            ValueError: If file too large or unsupported format.
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > MAX_IMAGE_SIZE_MB:
            raise ValueError(f"Image too large: {size_mb:.1f}MB (max {MAX_IMAGE_SIZE_MB}MB)")

        supported = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".pdf"}
        if path.suffix.lower() not in supported:
            raise ValueError(f"Unsupported format: {path.suffix}")

        logger.info("Running OCR", path=str(path), size_mb=round(size_mb, 2))

        results = await asyncio.to_thread(self._extract_sync, image_path)

        logger.info("OCR completed", path=str(path), text_blocks=len(results))
        return results

    async def extract_all_text(self, image_path: str) -> str:
        """Extract all text as single string.

        Args:
            image_path: Path to image or PDF file.

        Returns:
            Concatenated text from all OCR results.
        """
        results = await self.extract_text(image_path)
        return "\n".join(r.text for r in results)
