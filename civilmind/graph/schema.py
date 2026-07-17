"""Neo4j graph schema — node labels, relationship types, and constraints.

Defines the knowledge graph structure for construction projects:
12 node types, 12 relationship types covering Building → Floor → Room →
Wall → Beam → Material → Vendor.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Node Labels ──────────────────────────────────────────────────────

NODE_LABELS: list[str] = [
    "Project",
    "Building",
    "Floor",
    "Room",
    "Wall",
    "Column",
    "Beam",
    "Door",
    "Window",
    "Material",
    "Vendor",
    "BuildingCode",
]

# Properties per node label (required + optional)
NODE_PROPERTIES: dict[str, list[str]] = {
    "Project": ["id", "name", "location"],
    "Building": ["id", "name", "area_sqm"],
    "Floor": ["id", "level", "name"],
    "Room": ["id", "name", "area_sqm", "type"],
    "Wall": ["id", "type", "thickness_mm"],
    "Column": ["id", "size_mm", "material"],
    "Beam": ["id", "size_mm", "span_m"],
    "Door": ["id", "type", "width_mm"],
    "Window": ["id", "type", "width_mm"],
    "Material": ["id", "name", "grade"],
    "Vendor": ["id", "name", "location"],
    "BuildingCode": ["id", "name", "section"],
}

# ── Relationship Types ───────────────────────────────────────────────

RELATIONSHIP_TYPES: list[str] = [
    "HAS_BUILDING",
    "HAS_FLOOR",
    "HAS_ROOM",
    "HAS_WALL",
    "HAS_COLUMN",
    "HAS_DOOR",
    "HAS_WINDOW",
    "SUPPORTS",
    "USES_MATERIAL",
    "SUPPLIED_BY",
    "FOLLOWS_CODE",
    "REFERENCES",
]

# (from_label, relationship, to_label) valid combinations
VALID_EDGES: list[tuple[str, str, str]] = [
    ("Project", "HAS_BUILDING", "Building"),
    ("Building", "HAS_FLOOR", "Floor"),
    ("Floor", "HAS_ROOM", "Room"),
    ("Room", "HAS_WALL", "Wall"),
    ("Wall", "HAS_DOOR", "Door"),
    ("Wall", "HAS_WINDOW", "Window"),
    ("Floor", "HAS_COLUMN", "Column"),
    ("Column", "SUPPORTS", "Beam"),
    ("Beam", "USES_MATERIAL", "Material"),
    ("Wall", "USES_MATERIAL", "Material"),
    ("Material", "SUPPLIED_BY", "Vendor"),
    ("Building", "FOLLOWS_CODE", "BuildingCode"),
]


@dataclass(frozen=True)
class GraphEntity:
    """Entity to insert into Neo4j."""

    label: str
    properties: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.label not in NODE_LABELS:
            raise ValueError(f"Unknown node label: {self.label}")
        if "id" not in self.properties:
            raise ValueError("Entity must have an 'id' property")


@dataclass(frozen=True)
class GraphRelationship:
    """Relationship to insert into Neo4j."""

    from_id: str
    to_id: str
    rel_type: str
    properties: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.rel_type not in RELATIONSHIP_TYPES:
            raise ValueError(f"Unknown relationship type: {self.rel_type}")


# Cypher constraints to run at startup (unique ID per label)
CONSTRAINT_QUERIES: list[str] = [
    f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
    for label in NODE_LABELS
]
