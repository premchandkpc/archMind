"""CodeSearchTool — building code and regulation lookup.

Searches a curated database of building codes, standards, and regulations.
Currently uses in-memory store; Phase 8.2 will add vector search.
"""

from __future__ import annotations

from typing import Any

import structlog

from civilmind.tools.base import BaseTool, ToolResult

logger = structlog.get_logger()

# Placeholder regulation database — will be replaced with vector search in Phase 8
REGULATIONS_DB: list[dict[str, str]] = [
    {
        "code": "IBC",
        "section": "1004.5",
        "title": "Maximum Occupant Load",
        "text": (
            "The occupant load of a floor or other portion of a building "
            "shall be determined by dividing the floor area by the occupant "
            "load factor."
        ),
        "source": "International Building Code 2021",
    },
    {
        "code": "IBC",
        "section": "903.2.1",
        "title": "Automatic Sprinkler Systems — Group A",
        "text": (
            "An automatic sprinkler system shall be provided throughout "
            "all new Group A occupancies."
        ),
        "source": "International Building Code 2021",
    },
    {
        "code": "ACI",
        "section": "318-19 5.3",
        "title": "Concrete Strength Requirements",
        "text": (
            "Concrete shall be designed to have adequate strength for the "
            "intended purpose. Specified compressive strength fc' shall be "
            "not less than 3000 psi for structural applications."
        ),
        "source": "ACI 318-19",
    },
    {
        "code": "ASCE",
        "section": "7-22 12.2",
        "title": "Seismic Base Shear",
        "text": (
            "The seismic base shear V shall be determined in accordance "
            "with the following equation: V = Cs x W, where Cs is the "
            "seismic response coefficient and W is the effective seismic "
            "weight."
        ),
        "source": "ASCE 7-22",
    },
    {
        "code": "IECC",
        "section": "C402.1.3",
        "title": "Insulation Requirements — Roof",
        "text": (
            "Roof insulation requirements for commercial buildings: "
            "minimum R-30 continuous insulation for climate zones 4-8."
        ),
        "source": "International Energy Conservation Code 2021",
    },
]


class CodeSearchTool(BaseTool):
    """Search building codes and regulations."""

    name = "code_search"
    description = "Search building codes and regulations"
    category = "knowledge"

    def __init__(self, regulations: list[dict[str, str]] | None = None) -> None:
        self._db = regulations or REGULATIONS_DB

    async def execute(
        self,
        query: str,
        code: str | None = None,
        section: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Search building codes by keyword, code name, or section.

        Args:
            query: Free-text search query.
            code: Filter by code name (e.g., "IBC", "ACI", "ASCE").
            section: Filter by section number (e.g., "1004.5").

        Returns:
            ToolResult with matching regulation entries.
        """
        results = []

        for entry in self._db:
            # Filter by code
            if code and entry["code"].upper() != code.upper():
                continue

            # Filter by section
            if section and entry["section"] != section:
                continue

            # Free-text search across text, title, section
            search_text = f"{entry['title']} {entry['text']} {entry['section']}".lower()
            if query.lower() not in search_text:
                continue

            results.append(entry)

        logger.info(
            "Code search completed",
            query=query,
            code=code,
            section=section,
            results_count=len(results),
        )

        return ToolResult(
            success=True,
            data=results,
            metadata={"total_regulations": len(self._db), "query": query},
        )
