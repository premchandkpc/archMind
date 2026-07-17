"""Neo4j graph store — CRUD operations for the knowledge graph.

Wraps the Neo4j async driver with construction-domain operations.
Handles constraints, entity creation, relationship management,
and graph traversal queries.
"""

from __future__ import annotations

from typing import Any

import structlog

from civilmind.graph.schema import (
    CONSTRAINT_QUERIES,
    GraphEntity,
    GraphRelationship,
)

logger = structlog.get_logger()


class Neo4jStore:
    """Neo4j async driver wrapper for the construction knowledge graph."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        self._uri = uri
        self._user = user
        self._password = password
        self._driver: Any = None

    def _get_driver(self) -> Any:
        """Lazy-load Neo4j async driver."""
        if self._driver is None:
            from neo4j import AsyncGraphDatabase

            self._driver = AsyncGraphDatabase.driver(
                self._uri, auth=(self._user, self._password)
            )
            logger.info("Neo4j driver created", uri=self._uri)
        return self._driver

    async def close(self) -> None:
        """Close the driver."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("Neo4j driver closed")

    async def create_constraints(self) -> None:
        """Create unique ID constraints for all node labels. Idempotent."""
        driver = self._get_driver()
        async with driver.session() as session:
            for query in CONSTRAINT_QUERIES:
                await session.run(query)
        logger.info("Neo4j constraints created")

    async def create_entity(self, entity: GraphEntity) -> str:
        """Create or update a node. Returns the entity ID.

        Uses MERGE to be idempotent — updates properties on conflict.
        """
        driver = self._get_driver()
        async with driver.session() as session:
            cypher = (
                f"MERGE (n:{entity.label} {{id: $id}}) "
                f"SET n += $props "
                f"RETURN n.id AS id"
            )
            result = await session.run(
                cypher,
                id=entity.properties["id"],
                props={k: v for k, v in entity.properties.items() if k != "id"},
            )
            record = await result.single()
            entity_id = record["id"] if record else entity.properties["id"]

        logger.debug("Created entity", label=entity.label, id=entity_id)
        return entity_id

    async def create_relationship(self, rel: GraphRelationship) -> None:
        """Create a relationship between two nodes by ID.

        Uses MATCH + MERGE to be idempotent.
        """
        driver = self._get_driver()
        async with driver.session() as session:
            cypher = (
                f"MATCH (a {{id: $from_id}}), (b {{id: $to_id}}) "
                f"MERGE (a)-[r:{rel.rel_type}]->(b) "
                f"SET r += $props"
            )
            await session.run(
                cypher,
                from_id=rel.from_id,
                to_id=rel.to_id,
                props=rel.properties,
            )

        logger.debug(
            "Created relationship",
            rel_type=rel.rel_type,
            from_id=rel.from_id,
            to_id=rel.to_id,
        )

    async def create_entities_batch(
        self,
        entities: list[GraphEntity],
        relationships: list[GraphRelationship],
    ) -> int:
        """Batch create entities and relationships.

        Args:
            entities: List of GraphEntity to create.
            relationships: List of GraphRelationship to create.

        Returns:
            Number of entities created.
        """
        driver = self._get_driver()
        count = 0

        async with driver.session() as session:
            for entity in entities:
                cypher = (
                    f"MERGE (n:{entity.label} {{id: $id}}) "
                    f"SET n += $props"
                )
                await session.run(
                    cypher,
                    id=entity.properties["id"],
                    props={k: v for k, v in entity.properties.items() if k != "id"},
                )
                count += 1

            for rel in relationships:
                cypher = (
                    f"MATCH (a {{id: $from_id}}), (b {{id: $to_id}}) "
                    f"MERGE (a)-[r:{rel.rel_type}]->(b) "
                    f"SET r += $props"
                )
                await session.run(
                    cypher,
                    from_id=rel.from_id,
                    to_id=rel.to_id,
                    props=rel.properties,
                )

        logger.info(
            "Batch created graph data",
            entities=count,
            relationships=len(relationships),
        )
        return count

    async def get_entity(self, label: str, entity_id: str) -> dict[str, Any] | None:
        """Get a single node by label and ID."""
        driver = self._get_driver()
        async with driver.session() as session:
            cypher = f"MATCH (n:{label} {{id: $id}}) RETURN n AS node"
            result = await session.run(cypher, id=entity_id)
            record = await result.single()
            if record is None:
                return None
            return dict(record["node"])

    async def query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Run an arbitrary Cypher query and return records as dicts.

        Args:
            cypher: Cypher query string.
            params: Optional query parameters.

        Returns:
            List of record dicts.
        """
        driver = self._get_driver()
        async with driver.session() as session:
            result = await session.run(cypher, params or {})
            return [dict(record) async for record in result]

    async def traverse(
        self,
        start_id: str,
        relationship: str,
        max_depth: int = 2,
        direction: str = "outgoing",
    ) -> list[dict[str, Any]]:
        """Traverse the graph from a starting node.

        Args:
            start_id: ID of the starting node.
            relationship: Relationship type to follow.
            max_depth: Maximum traversal depth.
            direction: "outgoing", "incoming", or "both".

        Returns:
            List of reachable nodes with their properties and path info.
        """
        arrow = {
            "outgoing": "-[r]->",
            "incoming": "<-[r]-",
            "both": "-[r]-",
        }.get(direction, "-[r]->")

        driver = self._get_driver()
        async with driver.session() as session:
            cypher = (
                f"MATCH path = (start {{id: $start_id}}){arrow}(end) "
                f"WHERE type(r) = $rel_type "
                f"AND length(path) <= $max_depth "
                f"RETURN end, length(path) AS depth, "
                f"[r IN relationships(path) | type(r)] AS rel_types "
                f"ORDER BY depth"
            )
            result = await session.run(
                cypher,
                start_id=start_id,
                rel_type=relationship,
                max_depth=max_depth,
            )
            return [dict(record) async for record in result]

    async def delete_project(self, project_id: str) -> int:
        """Delete all nodes and relationships belonging to a project.

        Uses the project_id property that all entities carry.
        Returns number of nodes deleted.
        """
        driver = self._get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (n {project_id: $project_id}) "
                "DETACH DELETE n "
                "RETURN count(n) AS deleted",
                project_id=project_id,
            )
            record = await result.single()
            deleted = record["deleted"] if record else 0

        logger.info("Deleted project graph", project_id=project_id, nodes_deleted=deleted)
        return deleted

    async def health_check(self) -> bool:
        """Check Neo4j connectivity."""
        try:
            driver = self._get_driver()
            await driver.verify_connectivity()
            return True
        except Exception:
            return False
