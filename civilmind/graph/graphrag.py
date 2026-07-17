"""GraphRAG — combines vector search with graph traversal.

The full GraphRAG pipeline:
  1. Vector search finds text-mentioning chunks
  2. Extract entity hints from chunks
  3. Graph traversal finds related entities + relationships
  4. Combine vector context + graph context
  5. LLM generates answer with rich, multi-hop evidence
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from civilmind.graph.neo4j_store import Neo4jStore
from civilmind.graph.traversal import GraphTraversal
from civilmind.llm.client import LLMClient, LLMMessage, LLMResult
from civilmind.pipeline.embedder import BaseEmbedder
from civilmind.vector.qdrant_store import QdrantStore

logger = structlog.get_logger()


@dataclass
class GraphContext:
    """Combined vector + graph context for LLM answer generation."""

    vector_chunks: list[dict[str, Any]] = field(default_factory=list)
    graph_entities: list[dict[str, Any]] = field(default_factory=list)
    graph_relationships: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_prompt(self) -> str:
        """Format context as LLM prompt section."""
        sections: list[str] = []

        if self.vector_chunks:
            sections.append("## Relevant Document Excerpts")
            for i, chunk in enumerate(self.vector_chunks[:5], 1):
                content = chunk.get("content", "")[:500]
                source = chunk.get("source", "unknown")
                sections.append(f"[{i}] ({source}): {content}")

        if self.graph_entities:
            sections.append("## Knowledge Graph Entities")
            for entity in self.graph_entities[:20]:
                label = entity.get("label", entity.get("__label__", ""))
                name = entity.get("name", entity.get("id", ""))
                sections.append(f"- {label}: {name}")

        if self.graph_relationships:
            sections.append("## Graph Relationships")
            for rel in self.graph_relationships[:15]:
                src = rel.get("from", "?")
                rel_type = rel.get("type", "?")
                tgt = rel.get("to", "?")
                sections.append(f"- {src} --[{rel_type}]--> {tgt}")

        if self.evidence:
            sections.append("## Supporting Evidence")
            for ev in self.evidence:
                sections.append(f"- {ev}")

        return "\n\n".join(sections) if sections else "No additional context found."


class GraphRAG:
    """Graph-enhanced RAG: vector search + graph traversal + LLM answer.

    Combines the strengths of semantic search (finds text mentions)
    with knowledge graph traversal (finds structured relationships)
    to provide richer context for LLM answer generation.
    """

    def __init__(
        self,
        neo4j: Neo4jStore,
        vector_store: QdrantStore,
        embedder: BaseEmbedder,
        llm: LLMClient,
    ) -> None:
        self._neo4j = neo4j
        self._vector = vector_store
        self._embedder = embedder
        self._llm = llm
        self._traversal = GraphTraversal(neo4j)

    async def retrieve(
        self,
        query: str,
        project_id: str,
        top_k: int = 5,
    ) -> GraphContext:
        """Retrieve combined vector + graph context.

        Args:
            query: User query.
            project_id: Project to search within.
            top_k: Number of vector results.

        Returns:
            GraphContext with merged vector and graph data.
        """
        context = GraphContext()

        # Step 1: Vector search
        query_vector = await self._embedder.embed(query)
        vector_results = await self._vector.search(
            collection="civilmind",
            query_vector=query_vector,
            filter_dict={"project_id": project_id},
            limit=top_k,
        )

        for r in vector_results:
            context.vector_chunks.append({
                "id": r.id,
                "content": r.payload.get("content", ""),
                "source": r.payload.get("document_id", "unknown"),
                "score": r.score,
            })

        # Step 2: Extract entity hints from chunks and query
        entity_hints = self._extract_entity_hints(query, context.vector_chunks)

        # Step 3: Graph traversal for each entity hint
        seen_entities: set[str] = set()
        for label, name in entity_hints:
            traversal = await self._traversal.find_paths(
                start_label=label,
                start_name=name,
                project_id=project_id,
                max_depth=2,
            )
            for entity in traversal.entities:
                eid = entity.get("id", "")
                if eid and eid not in seen_entities:
                    seen_entities.add(eid)
                    context.graph_entities.append(entity)

            context.evidence.extend(traversal.evidence)
            context.graph_relationships.extend(
                [
                    {"from": r.get("from", ""), "type": r.get("rel_type", r.get("type", "")),
                     "to": r.get("to", "")}
                    for r in traversal.relationships
                ]
            )

        logger.info(
            "GraphRAG retrieval complete",
            project_id=project_id,
            vector_chunks=len(context.vector_chunks),
            graph_entities=len(context.graph_entities),
            evidence_count=len(context.evidence),
        )

        return context

    async def answer(
        self,
        query: str,
        project_id: str,
    ) -> str:
        """Retrieve context and generate an LLM answer.

        Args:
            query: User question.
            project_id: Project context.

        Returns:
            LLM-generated answer string.
        """
        context = await self.retrieve(query, project_id)

        prompt = f"""You are an expert construction analyst. Answer the question using
the provided context from documents and knowledge graph.

Question: {query}

{context.to_prompt()}

Provide a clear, professional answer. Cite specific sources where possible."""

        result: LLMResult = await self._llm.chat(
            messages=[LLMMessage(role="user", content=prompt)],
        )

        return result.content

    @staticmethod
    def _extract_entity_hints(
        query: str,
        chunks: list[dict[str, Any]],
    ) -> list[tuple[str, str]]:
        """Extract (label, name) entity hints from query and chunks.

        Uses simple keyword matching to find potential graph entities.
        For production, this could use an LLM-based NER step.
        """
        import re

        hints: list[tuple[str, str]] = []

        # Extract material grades from query
        for match in re.finditer(r"\bM\d{1,3}\b", query):
            hints.append(("Material", match.group(0)))

        for match in re.finditer(r"\bFe\s?\d{2,3}\b", query):
            hints.append(("Material", match.group(0)))

        # Extract room-like names
        room_pattern = re.compile(r"\b(bedroom|living|kitchen|bathroom|office|hall)\b", re.I)
        for match in room_pattern.finditer(query):
            hints.append(("Room", match.group(0).title()))

        # Extract code references
        for match in re.finditer(r"\b(IS|NBC|ACI|ASCE)\s?\d[\d-]*\b", query):
            hints.append(("BuildingCode", match.group(0)))

        return hints[:10]  # limit to prevent excessive traversal
