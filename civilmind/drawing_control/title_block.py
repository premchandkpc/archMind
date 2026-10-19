"""Conservative title-block parsing for drawing PDFs.

The parser returns a match only when explicit sheet and revision labels are unambiguous.
Scanned pages and conflicting labels are routed to human review.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass

SHEET_PATTERNS = (
    re.compile(
        r"\\b(?:sheet\\s*(?:no\\.?|number|#)?|drawing\\s*(?:no\\.?|number|#))"
        r"\\s*[:#-]?\\s*([A-Z]{1,5}[-.]?\\d{1,5}(?:\\.\\d{1,3})?)\\b",
        re.I,
    ),
)
REVISION_PATTERN = re.compile(
    r"\\b(?:revision|rev\\.?|issue\\s*rev\\.?)"
    r"\\s*(?:(?:no\\.?|number)\\s*)?[:#-]?\\s*"
    r"([A-Z]{1,2}\\d{0,3}|\\d{1,3}|[A-Z]{1,3})(?![A-Z0-9/])",
    re.I,
)
PROJECT_PATTERN = re.compile(
    r"\\bproject\\s*(?:name|title)?\\s*[:#-]\\s*([^\\r\\n]{2,100})", re.I
)
REVISION_PLACEHOLDERS = {"-", "NA", "N/A", "NONE", "TBD", "UNKNOWN", "NOTAPPLICABLE"}


@dataclass(frozen=True, slots=True)
class TitleBlockResult:
    sheet_number: str | None
    revision_label: str | None
    project_name: str | None
    status: str
    confidence: float
    matched_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    candidate_sheet_numbers: tuple[str, ...]
    candidate_revision_labels: tuple[str, ...]
    ambiguous_fields: tuple[str, ...]
    extracted_text_length: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _distinct_candidates(patterns: Iterable[re.Pattern[str]], text: str) -> tuple[str, ...]:
    """Collect normalized, distinct explicit labels instead of trusting the first hit."""
    values: set[str] = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            candidate = match.group(1).strip(" .:-").upper()
            if candidate and candidate not in REVISION_PLACEHOLDERS:
                values.add(candidate)
    return tuple(sorted(values))


def parse_title_block_text(text: str) -> TitleBlockResult:
    """Extract explicit labels; conflicting or incomplete identities remain unmatched."""
    sheet_candidates = _distinct_candidates(SHEET_PATTERNS, text)
    revision_candidates = _distinct_candidates((REVISION_PATTERN,), text)
    sheet_number = sheet_candidates[0] if len(sheet_candidates) == 1 else None
    revision_label = revision_candidates[0] if len(revision_candidates) == 1 else None
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
        for name, candidates in (
            ("sheet_number", sheet_candidates),
            ("revision_label", revision_candidates),
        )
        if not candidates
    )
    ambiguous = tuple(
        name
        for name, candidates in (
            ("sheet_number", sheet_candidates),
            ("revision_label", revision_candidates),
        )
        if len(candidates) > 1
    )
    status = "matched" if sheet_number and revision_label else "unmatched"
    confidence = 0.95 if status == "matched" else (0.25 if sheet_candidates or revision_candidates else 0.0)

    return TitleBlockResult(
        sheet_number=sheet_number,
        revision_label=revision_label,
        project_name=project_name,
        status=status,
        confidence=confidence,
        matched_fields=matched,
        missing_fields=missing,
        candidate_sheet_numbers=sheet_candidates,
        candidate_revision_labels=revision_candidates,
        ambiguous_fields=ambiguous,
        extracted_text_length=len(text),
    )
