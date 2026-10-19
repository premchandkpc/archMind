"""Conservative title-block parsing for drawing PDFs.

This parser extracts text only. Scanned PDFs or ambiguous title blocks are marked
unmatched for human review; it never guesses a sheet identity silently.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass

SHEET_PATTERNS = (
    re.compile(
        r"\b(?:sheet\s*(?:no\.?|number|#)?|drawing\s*(?:no\.?|number|#))"
        r"\s*[:#-]?\s*([A-Z]{1,5}[-.]?\d{1,5}(?:\.\d{1,3})?)\b",
        re.I,
    ),
)
REVISION_PATTERN = re.compile(
    r"\b(?:revision|rev\.?|issue\s*rev\.?)\s*[:#-]?\s*"
    r"([A-Z]{1,2}\d{0,3}|\d{1,3}|[A-Z]{1,3})\b",
    re.I,
)
PROJECT_PATTERN = re.compile(
    r"\bproject\s*(?:name|title)?\s*[:#-]\s*([^\r\n]{2,100})", re.I
)


@dataclass(frozen=True, slots=True)
class TitleBlockResult:
    sheet_number: str | None
    revision_label: str | None
    project_name: str | None
    status: str
    confidence: float
    matched_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    extracted_text_length: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _first_match(patterns: Iterable[re.Pattern[str]], text: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(1).strip(" .:-")
    return None


def parse_title_block_text(text: str) -> TitleBlockResult:
    """Extract explicit title-block labels from text extracted from a PDF."""
    normalized = " ".join(text.split())
    sheet_number = _first_match(SHEET_PATTERNS, normalized)
    revision_label = _first_match((REVISION_PATTERN,), normalized)
    project_match = PROJECT_PATTERN.search(text)
    project_name = project_match.group(1).strip() if project_match else None

    matched = tuple(
        name
        for name, value in (
            ("sheet_number", sheet_number),
            ("revision_label", revision_label),
            ("project_name", project_name),
        )
        if value
    )
    missing = tuple(
        name
        for name, value in (
            ("sheet_number", sheet_number),
            ("revision_label", revision_label),
            ("project_name", project_name),
        )
        if not value
    )
    # Only explicit sheet and revision labels qualify for automatic matching.
    status = "matched" if sheet_number and revision_label else "unmatched"
    confidence = 0.95 if status == "matched" else (0.5 if matched else 0.0)
    return TitleBlockResult(
        sheet_number=sheet_number,
        revision_label=revision_label,
        project_name=project_name,
        status=status,
        confidence=confidence,
        matched_fields=matched,
        missing_fields=missing,
        extracted_text_length=len(text),
    )
