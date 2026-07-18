"""Entity extraction — NER from documents and floor plan analysis.

Extracts construction entities (Building, Room, Material, etc.) from
parsed document elements and vision LLM output, then creates
GraphEntity / GraphRelationship objects for Neo4j ingestion.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from civilmind.graph.schema import GraphEntity, GraphRelationship

logger = structlog.get_logger()

# ── Material patterns ────────────────────────────────────────────────

MATERIAL_PATTERNS: list[tuple[str, str]] = [
    (r"\bM\d{1,3}\b", "Concrete"),
    (r"\bFe\s?\d{2,3}\b", "Steel"),
    (r"\bbrick\b", "Brick"),
    (r"\bmortar\b", "Mortar"),
    (r"\btile\b", "Tile"),
    (r"\bpipe\b", "Pipe"),
    (r"\bcable\b", "Cable"),
    (r"\brebar\b", "Reinforcement"),
    (r"\bformwork\b", "Formwork"),
    (r"\bgrout\b", "Grout"),
]

# ── Code reference patterns ──────────────────────────────────────────

CODE_PATTERNS: list[tuple[str, str]] = [
    (r"\bIS\s?\d{3,4}\b", "IS"),
    (r"\bNBC\s?\d{0,4}\b", "NBC"),
    (r"\bACI\s?\d[\d-]*\b", "ACI"),
    (r"\bASCE\s?\d[\d-]*\b", "ASCE"),
]


@dataclass
class ExtractedEntity:
    """Intermediate representation of an extracted entity."""

    label: str
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


@dataclass
class ExtractionResult:
    """Result of entity extraction from a single document/page."""

    entities: list[ExtractedEntity] = field(default_factory=list)
    relationships: list[GraphRelationship] = field(default_factory=list)


class EntityExtractor:
    """Extract construction entities from text and structured data.

    Uses regex patterns and heuristic rules for entity recognition.
    For higher accuracy, could be extended with an LLM-based NER step.
    """

    def extract_from_text(
        self,
        text: str,
        project_id: str,
        document_id: str = "",
    ) -> ExtractionResult:
        """Extract entities from raw text content.

        Args:
            text: Text content from a document chunk.
            project_id: Project these entities belong to.
            document_id: Source document ID.

        Returns:
            ExtractionResult with entities and relationships.
        """
        result = ExtractionResult()

        # Extract materials
        for pattern, material_name in MATERIAL_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                grade = match.group(0) if "M" in match.group(0) or "Fe" in match.group(0) else ""
                entity = ExtractedEntity(
                    label="Material",
                    name=material_name,
                    properties={
                        "id": f"mat-{uuid.uuid4().hex[:8]}",
                        "name": material_name,
                        "grade": grade,
                        "project_id": project_id,
                        "document_id": document_id,
                    },
                )
                result.entities.append(entity)

        # Extract building codes
        for pattern, code_name in CODE_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                entity = ExtractedEntity(
                    label="BuildingCode",
                    name=match.group(0),
                    properties={
                        "id": f"code-{uuid.uuid4().hex[:8]}",
                        "name": code_name,
                        "section": match.group(0),
                        "project_id": project_id,
                        "document_id": document_id,
                    },
                )
                result.entities.append(entity)

        logger.debug(
            "Extracted entities from text",
            document_id=document_id,
            entity_count=len(result.entities),
        )

        return result

    def extract_from_drawing_analysis(
        self,
        analysis: dict[str, Any],
        project_id: str,
        document_id: str = "",
    ) -> ExtractionResult:
        """Extract entities from floor plan analysis JSON.

        Args:
            analysis: Structured drawing analysis from FloorPlanAnalyzer.
            project_id: Project these entities belong to.
            document_id: Source document ID.

        Returns:
            ExtractionResult with entities and relationships.
        """
        result = ExtractionResult()
        result.entities.append(
            ExtractedEntity(
                label="Project",
                name=project_id,
                properties={"id": project_id, "name": project_id},
            )
        )

        # Building
        building_id = f"bld-{uuid.uuid4().hex[:8]}"
        building = ExtractedEntity(
            label="Building",
            name="Building",
            properties={
                "id": building_id,
                "name": "Building",
                "area_sqm": analysis.get("dimensions", {}).get("total_area_sqm", 0),
                "project_id": project_id,
            },
        )
        result.entities.append(building)
        result.relationships.append(
            GraphRelationship(from_id=project_id, to_id=building_id, rel_type="HAS_BUILDING")
        )

        # Floor → Rooms
        floor_id = f"floor-{uuid.uuid4().hex[:8]}"
        floor_entity = ExtractedEntity(
            label="Floor",
            name="Floor",
            properties={
                "id": floor_id,
                "level": 1,
                "name": "Ground Floor",
                "project_id": project_id,
            },
        )
        result.entities.append(floor_entity)
        result.relationships.append(
            GraphRelationship(from_id=building_id, to_id=floor_id, rel_type="HAS_FLOOR")
        )

        for room in analysis.get("rooms", []):
            room_id = f"room-{uuid.uuid4().hex[:8]}"
            room_entity = ExtractedEntity(
                label="Room",
                name=room.get("name", "Room"),
                properties={
                    "id": room_id,
                    "name": room.get("name", "Room"),
                    "area_sqm": room.get("area_sqm", 0),
                    "type": room.get("type", "general"),
                    "project_id": project_id,
                },
            )
            result.entities.append(room_entity)
            result.relationships.append(
                GraphRelationship(from_id=floor_id, to_id=room_id, rel_type="HAS_ROOM")
            )

        # Walls
        for wall in analysis.get("walls", []):
            wall_id = f"wall-{uuid.uuid4().hex[:8]}"
            wall_entity = ExtractedEntity(
                label="Wall",
                name="Wall",
                properties={
                    "id": wall_id,
                    "type": wall.get("type", "partition"),
                    "thickness_mm": wall.get("thickness_mm", 230),
                    "project_id": project_id,
                },
            )
            result.entities.append(wall_entity)

        # Columns
        for col in analysis.get("columns", []):
            col_id = col.get("id", f"col-{uuid.uuid4().hex[:8]}")
            col_entity = ExtractedEntity(
                label="Column",
                name=col_id,
                properties={
                    "id": col_id,
                    "size_mm": str(col.get("size_mm", "")),
                    "material": "RCC",
                    "project_id": project_id,
                },
            )
            result.entities.append(col_entity)
            result.relationships.append(
                GraphRelationship(from_id=floor_id, to_id=col_id, rel_type="HAS_COLUMN")
            )

        # Beams
        for beam in analysis.get("beams", []):
            beam_id = beam.get("id", f"beam-{uuid.uuid4().hex[:8]}")
            beam_entity = ExtractedEntity(
                label="Beam",
                name=beam_id,
                properties={
                    "id": beam_id,
                    "size_mm": str(beam.get("size_mm", "")),
                    "span_m": beam.get("span_m", 0),
                    "project_id": project_id,
                },
            )
            result.entities.append(beam_entity)

        # Doors
        for door in analysis.get("doors", []):
            door_id = door.get("id", f"door-{uuid.uuid4().hex[:8]}")
            door_entity = ExtractedEntity(
                label="Door",
                name=door_id,
                properties={
                    "id": door_id,
                    "type": door.get("type", "swing"),
                    "width_mm": door.get("width_mm", 900),
                    "project_id": project_id,
                },
            )
            result.entities.append(door_entity)

        # Windows
        for win in analysis.get("windows", []):
            win_id = win.get("id", f"win-{uuid.uuid4().hex[:8]}")
            win_entity = ExtractedEntity(
                label="Window",
                name=win_id,
                properties={
                    "id": win_id,
                    "type": win.get("type", "casement"),
                    "width_mm": win.get("width_mm", 1200),
                    "project_id": project_id,
                },
            )
            result.entities.append(win_entity)

        logger.info(
            "Extracted entities from drawing",
            document_id=document_id,
            entity_count=len(result.entities),
            relationship_count=len(result.relationships),
        )

        return result

    def to_graph_entities(
        self,
        extracted: list[ExtractedEntity],
    ) -> list[GraphEntity]:
        """Convert ExtractedEntity list to GraphEntity list for Neo4j."""
        return [GraphEntity(label=e.label, properties=e.properties) for e in extracted]
