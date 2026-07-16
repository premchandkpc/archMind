"""Metadata extraction — measurements, code references, technical keywords."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TECHNICAL_KEYWORDS: set[str] = {
    "concrete",
    "steel",
    "beam",
    "column",
    "slab",
    "foundation",
    "reinforcement",
    "load",
    "stress",
    "strain",
    "moment",
    "shear",
    "deflection",
    "crack",
    "cement",
    "aggregate",
    "brick",
    "mortar",
    "plaster",
    "tile",
    "paint",
    "pipe",
    "valve",
    "fitting",
    "duct",
    "cable",
    "rebar",
    "formwork",
    "curing",
    "grout",
    "masonry",
    "footing",
    "pile",
    "retaining",
    "waterproofing",
    "damp",
    "excavation",
    "backfill",
    "compaction",
    "subgrade",
}

MEASUREMENT_PATTERNS: list[str] = [
    r"\d+\.?\d*\s*(?:mm|cm|m|km|kg|g|mg|l|ml|sq\.?\s*m|cum)",
    r"\d+\.?\d*\s*(?:x|×)\s*\d+\.?\d*\s*(?:mm|cm|m)",
    r"M\d+",
    r"Fe\d+",
    r"\d+\.?\d*\s*(?:MPa|GPa|N/mm2)",
]

CODE_PATTERNS: list[str] = [
    r"IS\s*\d+",
    r"NBC\s*\d*",
    r"CPWD",
    r"SECTION\s*\d+",
    r"CLAUSE\s*\d+",
]

_measurement_regexes = [re.compile(p, re.IGNORECASE) for p in MEASUREMENT_PATTERNS]
_code_regexes = [re.compile(p, re.IGNORECASE) for p in CODE_PATTERNS]


@dataclass
class TextMetadata:
    char_count: int = 0
    word_count: int = 0
    has_numbers: bool = False
    has_measurements: bool = False
    measurements: list[str] = field(default_factory=list)
    has_code_references: bool = False
    code_references: list[str] = field(default_factory=list)
    language: str = "en"
    keywords: set[str] = field(default_factory=set)
    is_technical: bool = False


def extract_metadata(text: str) -> TextMetadata:
    if not text or not text.strip():
        return TextMetadata()

    meta = TextMetadata(
        char_count=len(text),
        word_count=len(text.split()),
        has_numbers=bool(re.search(r"\d", text)),
    )

    for regex in _measurement_regexes:
        for match in regex.findall(text):
            cleaned = match.strip()
            if cleaned:
                meta.measurements.append(cleaned)

    meta.has_measurements = bool(meta.measurements)

    for regex in _code_regexes:
        for match in regex.findall(text):
            cleaned = match.strip().upper()
            if cleaned:
                meta.code_references.append(cleaned)

    meta.has_code_references = bool(meta.code_references)

    words = set(re.findall(r"[a-zA-Z]+", text.lower()))
    meta.keywords = words & TECHNICAL_KEYWORDS
    meta.is_technical = bool(meta.keywords)

    return meta
