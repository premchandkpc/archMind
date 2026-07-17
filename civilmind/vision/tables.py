"""Table extractor — extracts tables from PDFs and images.

Classifies tables as BOQ, spec, schedule, or cost breakdown.
Uses pdfplumber for PDFs and vision LLM for images.
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import structlog

from civilmind.settings import settings

logger = structlog.get_logger()

BOQ_KEYWORDS = [
    "bill of quantities",
    "boq",
    "schedule of rates",
    "item",
    "quantity",
    "unit",
    "rate",
    "amount",
]

SPEC_KEYWORDS = [
    "material",
    "property",
    "value",
    "grade",
    "strength",
    "specification",
    "compliance",
    "standard",
]

SCHEDULE_KEYWORDS = [
    "task",
    "duration",
    "start",
    "end",
    "dependency",
    "milestone",
    "activity",
    "wbs",
]


class TableType(StrEnum):
    """Classification of extracted tables."""

    BOQ = "boq"
    SPEC = "spec"
    SCHEDULE = "schedule"
    COST = "cost"
    UNKNOWN = "unknown"


@dataclass
class ExtractedTable:
    """Single extracted table."""

    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    table_type: TableType = TableType.UNKNOWN
    page: int | None = None
    confidence: float = 0.0
    source_path: str = ""


class TableExtractor:
    """Extracts and classifies tables from construction documents.

    Uses pdfplumber for PDF table extraction and vision LLM for images.
    Classifies tables into BOQ, spec, schedule, or cost breakdown.
    """

    def __init__(self, vision_model: str | None = None) -> None:
        self._vision_model = vision_model or settings.LLM_VISION_MODEL

    def _classify_table(self, headers: list[str]) -> TableType:
        """Classify table based on headers."""
        header_text = " ".join(headers).lower()

        scores = {
            TableType.BOQ: sum(1 for kw in BOQ_KEYWORDS if kw in header_text),
            TableType.SPEC: sum(1 for kw in SPEC_KEYWORDS if kw in header_text),
            TableType.SCHEDULE: sum(1 for kw in SCHEDULE_KEYWORDS if kw in header_text),
        }

        if scores[TableType.BOQ] >= 3:
            return TableType.BOQ
        if scores[TableType.SPEC] >= 2:
            return TableType.SPEC
        if scores[TableType.SCHEDULE] >= 2:
            return TableType.SCHEDULE

        return TableType.UNKNOWN

    def _extract_from_pdf_sync(self, pdf_path: str) -> list[ExtractedTable]:
        """Synchronous PDF table extraction using pdfplumber."""
        tables: list[ExtractedTable] = []

        try:
            import pdfplumber
        except ImportError:
            logger.error("pdfplumber not installed", hint="pip install pdfplumber")
            return tables

        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                page_tables = page.extract_tables()
                for table_data in page_tables:
                    if not table_data or len(table_data) < 2:
                        continue

                    headers = [str(h or "").strip() for h in table_data[0]]
                    rows = [[str(cell or "").strip() for cell in row] for row in table_data[1:]]

                    table_type = self._classify_table(headers)

                    tables.append(
                        ExtractedTable(
                            headers=headers,
                            rows=rows,
                            table_type=table_type,
                            page=page_num + 1,
                            confidence=0.9,
                            source_path=pdf_path,
                        )
                    )

        logger.info("PDF tables extracted", path=pdf_path, count=len(tables))
        return tables

    async def extract_from_pdf(self, pdf_path: str) -> list[ExtractedTable]:
        """Extract tables from PDF.

        Args:
            pdf_path: Path to PDF file.

        Returns:
            List of ExtractedTable with classified tables.
        """
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        return await asyncio.to_thread(self._extract_from_pdf_sync, pdf_path)

    async def _call_vision_for_tables(self, image_b64: str) -> list[ExtractedTable]:
        """Use vision LLM to extract tables from image."""
        import httpx

        prompt = """Extract ALL tables from this image as JSON.

Return format:
{
    "tables": [
        {
            "headers": ["col1", "col2"],
            "rows": [["val1", "val2"]],
            "type_hint": "boq|spec|schedule|cost|unknown"
        }
    ]
}

Return ONLY valid JSON. No markdown fences."""

        api_key = settings.LLM_API_KEY
        base_url = settings.LLM_BASE_URL

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self._vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
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
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

        data = response.json()
        content = data["choices"][0]["message"]["content"]

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content[:-3]
            parsed = json.loads(content)

        tables: list[ExtractedTable] = []
        for t in parsed.get("tables", []):
            headers = t.get("headers", [])
            rows = t.get("rows", [])
            type_hint = t.get("type_hint", "unknown")

            table_type = (
                TableType(type_hint)
                if type_hint in TableType.__members__.values()
                else self._classify_table(headers)
            )

            tables.append(
                ExtractedTable(
                    headers=headers,
                    rows=rows,
                    table_type=table_type,
                    confidence=0.7,
                )
            )

        return tables

    async def extract_from_image(self, image_path: str) -> list[ExtractedTable]:
        """Extract tables from image using vision LLM.

        Args:
            image_path: Path to image file.

        Returns:
            List of ExtractedTable found in image.
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        data = await asyncio.to_thread(path.read_bytes)
        image_b64 = base64.b64encode(data).decode("utf-8")

        tables = await self._call_vision_for_tables(image_b64)

        for t in tables:
            t.source_path = image_path

        logger.info("Image tables extracted", path=image_path, count=len(tables))
        return tables

    def to_boq_json(self, table: ExtractedTable) -> dict[str, Any]:
        """Convert BOQ table to structured JSON.

        Args:
            table: ExtractedTable with table_type == BOQ.

        Returns:
            Structured BOQ with items and total.
        """
        items: list[dict[str, Any]] = []
        total = 0.0

        for row in table.rows:
            if len(row) >= 5:
                item = {
                    "item": row[0],
                    "qty": float(row[1]) if row[1].replace(".", "").isdigit() else 0,
                    "unit": row[2],
                    "rate": float(row[3]) if row[3].replace(".", "").isdigit() else 0,
                    "amount": float(row[4]) if row[4].replace(".", "").isdigit() else 0,
                }
                total += item["amount"]
                items.append(item)

        return {"items": items, "total": total, "currency": "INR"}
