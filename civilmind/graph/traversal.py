"""Graph traversal — multi-hop reasoning over the Neo4j knowledge graph.

Combines vector search results with graph traversal to answer
complex questions like "What vendor supplies concrete for Bedroom 1?".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from civilmind.graph.neo4j_store import Neo4jStore

logger = structlog.get_logger()

# Maximum hops for multi-hop queries
DEFAULT_MAX_HOPS = 3


@dataclass
class GraphPath:
    """A single path found during graph traversal."""

    nodes: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[str] = field(default_factory=list)
    length: int = 0


@dataclass
class TraversalResult:
    """Result of a graph traversal query."""

    paths: list[GraphPath] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)

    @property
    def evidence(self) -> list[str]:
        """Human-readable evidence strings from the traversal."""
        evidence: list[str] = []
        for path in self.paths:
            if len(path.nodes) >= 2:
                names = [n.get("name", n.get("id", "?")) for n in path.nodes]
                rels = " → ".join(
                    f"{names[i]} --{path.relationships[i]}--> {names[i+1]}"
                    for i in range(min(len(path.relationships), len(names) - 1))
                )
                evidence.append(rels)
        return evidence


class GraphTraversal:
    """Multi-hop graph traversal for construction knowledge graph.

    Given entities from vector search or user query, traverses
    the Neo4j graph to find related entities and relationships.
    """

    def __init__(self, store: Neo4jStore) -> None:
        self._store = store

    async def find_paths(
        self,
        start_label: str,
        start_name: str,
        project_id: str,
        max_depth: int = DEFAULT_MAX_HOPS,
    ) -> TraversalResult:
        """Find all paths from a named entity.

        Args:
            start_label: Neo4j node label (e.g., "Room", "Material").
            start_name: Name or ID of the starting entity.
            project_id: Limit traversal to this project.

            max_depth: Maximum hops.

        Returns:
            TraversalResult with discovered paths and entities.
        """
        result = TraversalResult()

        # Find the starting node
        start_entities = await self._store.query(
            f"MATCH (n:{start_label}) "
            "WHERE (n.name = $name OR n.id = $name) "
            "AND n.project_id = $project_id "
            "RETURN n LIMIT 1",
            {"name": start_name, "project_id": project_id},
        )

        if not start_entities:
            logger.debug("No starting entity found", label=start_label, name=start_name)
            return result

        start_id = start_entities[0].get("n", {}).get("id", "")
        if not start_id:
            return result

        # Traverse outward up to max_depth
        paths_data = await self._store.traverse(
            start_id=start_id,
            relationship="",  # empty = any relationship
            max_depth=max_depth,
            direction="both",
        )

        for path_record in paths_data:
            end_node = path_record.get("end", {})
            depth = path_record.get("depth", 0)
            rel_types = path_record.get("rel_types", [])

            graph_path = GraphPath(
                nodes=[
                    {"id": start_id, "name": start_name, "label": start_label},
                    {
                        "id": end_node.get("id", ""),
                        "name": end_node.get("name", end_node.get("id", "")),
                        "label": end_node.get("__label__", ""),
                    },
                ],
                relationships=rel_types,
                length=depth,
            )
            result.paths.append(graph_path)
            result.entities.append(end_node)

        logger.info(
            "Graph traversal completed",
            start_label=start_label,
            start_name=start_name,
            paths_found=len(result.paths),
        )

        return result

    async def find_material_chain(
        self,
        room_name: str,
        project_id: str,
    ) -> TraversalResult:
        """Find the material → vendor chain for a room.

        Traverses: Room → Wall → Material → Vendor

        Args:
            room_name: Name of the room (e.g., "Bedroom 1").
            project_id: Project ID.

        Returns:
            TraversalResult with material and vendor entities.
        """
        result = TraversalResult()

        # Find room → wall → material → vendor chain
        chain = await self._store.query(
            "MATCH (room:Room)-[:HAS_WALL]->(wall:Wall)-[:USES_MATERIAL]->(mat:Material)"
            "-[:SUPPLIED_BY]->(vendor:Vendor) "
            "WHERE (room.name = $room_name OR room.id = $room_name) "
            "AND room.project_id = $project_id "
            "RETURN room, wall, mat, vendor",
            {"room_name": room_name, "project_id": project_id},
        )

        for record in chain:
            mat = record.get("mat", {})
            vendor = record.get("vendor", {})
            wall = record.get("wall", {})

            result.entities.extend([mat, vendor, wall])
            result.relationships.append({
                "from": wall.get("id", ""),
                "type": "USES_MATERIAL",
                "to": mat.get("id", ""),
            })
            result.relationships.append({
                "from": mat.get("id", ""),
                "type": "SUPPLIED_BY",
                "to": vendor.get("id", ""),
            })

            result.paths.append(GraphPath(
                nodes=[
                    {"id": record.get("room", {}).get("id", ""), "label": "Room"},
                    {"id": wall.get("id", ""), "label": "Wall"},
                    {"id": mat.get("id", ""), "name": mat.get("name", ""), "label": "Material"},
                    {"id": vendor.get("id", ""), "name": vendor.get("name", ""), "label": "Vendor"},
                ],
                relationships=["HAS_WALL", "USES_MATERIAL", "SUPPLIED_BY"],
                length=3,
            ))

        logger.info(
            "Material chain found",
            room_name=room_name,
            chains=len(result.paths),
        )

        return result

    async def find_building_codes(
        self,
        entity_name: str,
        project_id: str,
    ) -> TraversalResult:
        """Find building codes applicable to an entity.

        Traverses: Building → FOLLOWS_CODE → BuildingCode

        Args:
            entity_name: Building or entity name.
            project_id: Project ID.

        Returns:
            TraversalResult with applicable building codes.
        """
        result = TraversalResult()

        codes = await self._store.query(
            "MATCH (b:Building)-[:FOLLOWS_CODE]->(code:BuildingCode) "
            "WHERE (b.name = $name OR b.id = $name) "
            "AND b.project_id = $project_id "
            "RETURN b, code",
            {"name": entity_name, "project_id": project_id},
        )

        for record in codes:
            code_node = record.get("code", {})
            result.entities.append(code_node)
            result.paths.append(GraphPath(
                nodes=[
                    {"id": record.get("b", {}).get("id", ""), "label": "Building"},
                    {"id": code_node.get("id", ""),
                     "name": code_node.get("name", ""),
                     "label": "BuildingCode"},
                ],
                relationships=["FOLLOWS_CODE"],
                length=1,
            ))

        return result

    async def get_full_context(
        self,
        project_id: str,
        max_nodes: int = 100,
    ) -> TraversalResult:
        """Get the full knowledge graph context for a project.

        Returns all entities and relationships for the project,
        useful for building rich LLM context.

        Args:
            project_id: Project ID.
            max_nodes: Maximum nodes to return.

        Returns:
            TraversalResult with all project graph data.
        """
        result = TraversalResult()

        nodes = await self._store.query(
            "MATCH (n {project_id: $project_id}) "
            "RETURN labels(n)[0] AS label, n "
            "LIMIT $limit",
            {"project_id": project_id, "limit": max_nodes},
        )

        for record in nodes:
            node_data = record.get("n", {})
            node_data["label"] = record.get("label", "")
            result.entities.append(node_data)

        relationships = await self._store.query(
            "MATCH (a {project_id: $project_id})-[r]->(b {project_id: $project_id}) "
            "RETURN a.id AS from_id, type(r) AS rel_type, b.id AS to_id "
            "LIMIT $limit",
            {"project_id": project_id, "limit": max_nodes},
        )

        result.relationships = [
            {
                "from_id": r.get("from_id", ""),
                "rel_type": r.get("rel_type", ""),
                "to_id": r.get("to_id", ""),
            }
            for r in relationships
        ]

        logger.info(
            "Full project context loaded",
            project_id=project_id,
            nodes=len(result.entities),
            relationships=len(result.relationships),
        )

        return result
