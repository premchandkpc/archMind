"""Floor plan analyzer — vision LLM for structural element detection.

Uses OpenCode Zen vision models to analyze construction drawings.
Extracts walls, columns, beams, doors, windows, rooms, and dimensions.
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from civilmind.settings import settings

logger = structlog.get_logger()

FLOOR_PLAN_PROMPT = """Analyze this construction drawing. Extract ALL elements as JSON:

{
    "drawing_type": "floor_plan|structural|electrical|plumbing",
    "rooms": [{"name": "Living Room", "area_sqm": 25.0}],
    "walls": [{"type": "load_bearing|partition", "thickness_mm": 230}],
    "doors": [{"id": "D1", "type": "swing|sliding", "width_mm": 900}],
    "windows": [{"id": "W1", "type": "casement", "width_mm": 1200}],
    "columns": [{"id": "C1", "size_mm": {"width": 300, "depth": 300}}],
    "beams": [{"id": "B1", "size_mm": {"width": 230, "depth": 450}, "span_m": 4.0}],
    "dimensions": {"total_area_sqm": 180.0},
    "notes": ["any text annotations"]
}

Return ONLY valid JSON. No markdown fences."""


@dataclass
class DrawingAnalysis:
    """Structured analysis of a construction drawing."""

    drawing_type: str = "unknown"
    rooms: list[dict[str, Any]] = field(default_factory=list)
    walls: list[dict[str, Any]] = field(default_factory=list)
    doors: list[dict[str, Any]] = field(default_factory=list)
    windows: list[dict[str, Any]] = field(default_factory=list)
    columns: list[dict[str, Any]] = field(default_factory=list)
    beams: list[dict[str, Any]] = field(default_factory=list)
    dimensions: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    raw_json: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DrawingAnalysis:
        return cls(
            drawing_type=data.get("drawing_type", "unknown"),
            rooms=data.get("rooms", []),
            walls=data.get("walls", []),
            doors=data.get("doors", []),
            windows=data.get("windows", []),
            columns=data.get("columns", []),
            beams=data.get("beams", []),
            dimensions=data.get("dimensions", {}),
            notes=data.get("notes", []),
            raw_json=data,
        )


class FloorPlanAnalyzer:
    """Vision LLM analyzer for construction drawings.

    Uses OpenCode Zen (GPT-5, Claude) to detect structural elements
    from floor plans, sections, and elevations.
    """

    def __init__(self, model: str | None = None) -> None:
        self._model = model or settings.LLM_VISION_MODEL
        self._api_key = settings.LLM_API_KEY
        self._base_url = settings.LLM_BASE_URL

    async def _encode_image(self, image_path: str) -> str:
        """Read and base64-encode image file."""
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        data = await asyncio.to_thread(path.read_bytes)
        return base64.b64encode(data).decode("utf-8")

    async def _call_vision_api(self, image_b64: str) -> dict[str, Any]:
        """Call vision LLM API with image."""
        import httpx

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": FLOOR_PLAN_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                }
            ],
            "max_tokens": 4000,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

        data = response.json()
        content = data["choices"][0]["message"]["content"]

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content[:-3]
            return json.loads(content)

    async def analyze(self, image_path: str) -> DrawingAnalysis:
        """Analyze construction drawing using vision LLM.

        Args:
            image_path: Path to drawing image (PNG, JPG, etc.).

        Returns:
            DrawingAnalysis with extracted structural elements.

        Raises:
            FileNotFoundError: If image doesn't exist.
            ValueError: If API call fails.
        """
        logger.info("Analyzing floor plan", path=image_path, model=self._model)

        image_b64 = await self._encode_image(image_path)

        try:
            raw_data = await self._call_vision_api(image_b64)
        except Exception as e:
            logger.error("Vision API call failed", error=str(e))
            raise ValueError(f"Vision analysis failed: {e}") from e

        analysis = DrawingAnalysis.from_dict(raw_data)
        analysis.confidence = 0.8

        logger.info(
            "Floor plan analyzed",
            drawing_type=analysis.drawing_type,
            rooms=len(analysis.rooms),
            columns=len(analysis.columns),
        )

        return analysis

    async def analyze_batch(self, image_paths: list[str]) -> list[DrawingAnalysis]:
        """Analyze multiple drawings.

        Args:
            image_paths: List of image paths.

        Returns:
            List of DrawingAnalysis for each image.
        """
        tasks = [self.analyze(path) for path in image_paths]
        return await asyncio.gather(*tasks)
