"""Document parser — converts raw files into ParsedElement objects.

Supported formats: PDF, DOCX, XLSX, PNG, JPG.
For scanned PDFs, falls back to PaddleOCR.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import structlog

logger = structlog.get_logger()

TEMP_IMAGE_DIR = Path(tempfile.gettempdir()) / "civilmind_images"


class ElementType(Enum):
    TITLE = "title"
    NARRATIVE = "narrative"
    TABLE = "table"
    IMAGE = "image"
    LIST = "list"
    PAGE_BREAK = "page_break"
    UNKNOWN = "unknown"


@dataclass
class ParsedElement:
    type: ElementType
    content: str
    metadata: dict[str, object] = field(default_factory=dict)
    table_data: list[list[str]] | None = None
    image_path: str | None = None
    page_number: int | None = None


class DocumentParser:
    """Parse documents into structured elements."""

    def __init__(self) -> None:
        self._ocr_engine: Any = None

    def _get_ocr_engine(self) -> Any:
        if self._ocr_engine is None:
            try:
                from paddleocr import PaddleOCR

                self._ocr_engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
            except ImportError:
                logger.warning("PaddleOCR not available, OCR disabled")
                self._ocr_engine = MagicMock()
                self._ocr_engine.ocr.return_value = None
        return self._ocr_engine

    async def parse(self, file_path: str) -> list[ParsedElement]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._parse_pdf(path)
        if suffix == ".docx":
            return self._parse_docx(path)
        if suffix == ".xlsx":
            return self._parse_xlsx(path)
        if suffix in (".png", ".jpg", ".jpeg"):
            return self._parse_image(path)
        raise ValueError(f"Unsupported format: {suffix}")

    def _parse_pdf(self, path: Path) -> list[ParsedElement]:
        try:
            from unstructured.partition.pdf import partition_pdf
        except ImportError:
            logger.error("unstructured not installed, install with: pip install unstructured[pdf]")
            return self._fallback_ocr_pdf(path)

        TEMP_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

        try:
            elements = partition_pdf(
                filename=str(path),
                extract_images_in_pdf=True,
                image_output_dir_path=str(TEMP_IMAGE_DIR),
                strategy="hi_res",
            )
        except Exception as e:
            logger.warning("Unstructured PDF parsing failed, falling back to OCR", error=str(e))
            return self._fallback_ocr_pdf(path)

        result: list[ParsedElement] = []
        for el in elements:
            el_type = self._classify_element(el)
            if el_type == ElementType.PAGE_BREAK:
                continue

            page_number = getattr(el.metadata, "page_number", None)
            table_data = None
            image_path = None

            if el_type == ElementType.TABLE:
                table_data = self._extract_table_data(el)

            if el_type == ElementType.IMAGE:
                image_path = self._extract_image_path(el, path)

            result.append(
                ParsedElement(
                    type=el_type,
                    content=str(el.text or ""),
                    page_number=page_number,
                    table_data=table_data,
                    image_path=image_path,
                    metadata={
                        "element_index": getattr(el.metadata, "element_index", None),
                        "char_count": len(str(el.text or "")),
                    },
                )
            )

        return result

    def _fallback_ocr_pdf(self, path: Path) -> list[ParsedElement]:
        logger.info("Using OCR fallback for PDF", file=str(path))
        engine = self._get_ocr_engine()
        result = engine.ocr(str(path), cls=True)

        if not result or not result[0]:
            return []

        text_lines = []
        for line in result[0]:
            _bbox, (text, confidence) = line
            if confidence >= 0.5:
                text_lines.append(text)

        full_text = "\n".join(text_lines)
        return [
            ParsedElement(
                type=ElementType.NARRATIVE,
                content=full_text,
                metadata={"source": "ocr_fallback", "char_count": len(full_text)},
            )
        ]

    def _parse_docx(self, path: Path) -> list[ParsedElement]:
        try:
            from unstructured.partition.docx import partition_docx
        except ImportError:
            raise ImportError("unstructured not installed")

        elements = partition_docx(filename=str(path))

        result: list[ParsedElement] = []
        for el in elements:
            el_type = self._classify_element(el)

            table_data = None
            if el_type == ElementType.TABLE:
                table_data = self._extract_table_data(el)

            result.append(
                ParsedElement(
                    type=el_type,
                    content=str(el.text or ""),
                    table_data=table_data,
                    metadata={"char_count": len(str(el.text or ""))},
                )
            )

        return result

    def _parse_xlsx(self, path: Path) -> list[ParsedElement]:
        try:
            xls = pd.ExcelFile(path)
        except Exception as e:
            logger.error("Failed to read Excel file", error=str(e))
            return []

        result: list[ParsedElement] = []
        for sheet_name in xls.sheet_names:
            df = pd.read_excel(path, sheet_name=sheet_name)
            df = df.dropna(how="all").fillna("")

            if df.empty:
                continue

            table_data = [df.columns.astype(str).tolist()]
            table_data.extend(df.astype(str).values.tolist())

            result.append(
                ParsedElement(
                    type=ElementType.TABLE,
                    content=f"Sheet: {sheet_name}",
                    table_data=table_data,
                    metadata={"sheet_name": sheet_name, "rows": len(table_data) - 1},
                )
            )

        return result

    def _parse_image(self, path: Path) -> list[ParsedElement]:
        engine = self._get_ocr_engine()
        result = engine.ocr(str(path), cls=True)

        image_element = ParsedElement(
            type=ElementType.IMAGE,
            content=f"[Image: {path.name}]",
            image_path=str(path),
            metadata={"file_name": path.name, "file_size": path.stat().st_size},
        )

        elements: list[ParsedElement] = [image_element]

        if result and result[0]:
            text_lines = []
            for line in result[0]:
                _bbox, (text, confidence) = line
                if confidence >= 0.5:
                    text_lines.append(text)

            if text_lines:
                elements.append(
                    ParsedElement(
                        type=ElementType.NARRATIVE,
                        content="\n".join(text_lines),
                        metadata={"source": "ocr", "char_count": len("".join(text_lines))},
                    )
                )

        return elements

    @staticmethod
    def _classify_element(element: Any) -> ElementType:
        class_name = type(element).__name__.lower()
        if "title" in class_name:
            return ElementType.TITLE
        if "narrative" in class_name:
            return ElementType.NARRATIVE
        if "table" in class_name:
            return ElementType.TABLE
        if "image" in class_name:
            return ElementType.IMAGE
        if "list" in class_name:
            return ElementType.LIST
        if "pagebreak" in class_name:
            return ElementType.PAGE_BREAK
        return ElementType.UNKNOWN

    @staticmethod
    def _extract_table_data(element: Any) -> list[list[str]]:
        try:
            if hasattr(element, "metadata") and hasattr(element.metadata, "text_as_html"):
                html = element.metadata.text_as_html
                if html:
                    import re

                    rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)
                    table = []
                    for row in rows:
                        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)
                        table.append([re.sub(r"<[^>]+>", "", c).strip() for c in cells])
                    return table
        except Exception:
            pass
        return []

    @staticmethod
    def _extract_image_path(element: Any, doc_path: Path) -> str | None:
        try:
            if hasattr(element, "metadata") and hasattr(element.metadata, "image_path"):
                img_path = element.metadata.image_path
                if img_path and os.path.exists(img_path):
                    return str(img_path)
        except Exception:
            pass
        return None
