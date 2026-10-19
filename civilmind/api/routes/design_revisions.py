"""Stateless design revision analysis endpoint."""

from __future__ import annotations

from dataclasses import asdict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from civilmind.design_versioning import (
    DesignObject,
    DesignSnapshot,
    ImpactGraph,
    JsonValue,
    Relationship,
    compare_relationships,
    compare_snapshots,
    evaluate_minimum_rules,
)

router = APIRouter(prefix="/design-revisions", tags=["design-revisions"])


class DesignObjectPayload(BaseModel):
    """Adapter-normalized object in a submitted revision."""

    model_config = ConfigDict(extra="forbid")

    object_id: str = Field(min_length=1, max_length=512)
    kind: str = Field(min_length=1, max_length=128)
    properties: dict[str, JsonValue] = Field(default_factory=dict)
    source_id: str | None = Field(default=None, max_length=512)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class RelationshipPayload(BaseModel):
    """A directed relationship where changes to source may affect target."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=512)
    target_id: str = Field(min_length=1, max_length=512)
    relation_type: str = Field(min_length=1, max_length=128)
    provenance: str = Field(min_length=1, max_length=512)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class SnapshotPayload(BaseModel):
    """Normalized snapshot from one source revision."""

    model_config = ConfigDict(extra="forbid")

    revision_id: str = Field(min_length=1, max_length=512)
    objects: list[DesignObjectPayload] = Field(max_length=100_000)
    relationships: list[RelationshipPayload] = Field(default_factory=list, max_length=500_000)


class AnalyzeRevisionRequest(BaseModel):
    """Input for a stateless comparison; no files or revisions are persisted."""

    model_config = ConfigDict(extra="forbid")

    base: SnapshotPayload
    head: SnapshotPayload
    minimum_room_area_sqm: float | None = Field(default=None, ge=0.0)
    minimum_door_width_mm: float | None = Field(default=None, ge=0.0)
    max_impact_depth: int = Field(default=3, ge=0, le=10)
    min_relationship_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


def _to_snapshot(payload: SnapshotPayload) -> DesignSnapshot:
    """Convert validated transport objects into the domain model."""
    try:
        return DesignSnapshot(
            revision_id=payload.revision_id,
            objects=tuple(
                DesignObject(
                    object_id=obj.object_id,
                    kind=obj.kind,
                    properties=obj.properties,
                    source_id=obj.source_id,
                    confidence=obj.confidence,
                )
                for obj in payload.objects
            ),
            relationships=tuple(
                Relationship(
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    relation_type=edge.relation_type,
                    provenance=edge.provenance,
                    confidence=edge.confidence,
                )
                for edge in payload.relationships
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/analyze")
async def analyze_revision(request: AnalyzeRevisionRequest) -> dict[str, object]:
    """Compare two normalized snapshots and return evidence-backed candidates."""
    base = _to_snapshot(request.base)
    head = _to_snapshot(request.head)
    changes = compare_snapshots(base, head)
    relationship_changes = compare_relationships(base, head)
    changed_ids = {change.object_id for change in changes}
    for change in relationship_changes:
        changed_ids.add(change.source_id)
        changed_ids.add(change.target_id)

    # Include both revision edge sets so removals can still surface dependencies that
    # existed before the edit. The result is a candidate impact list, not a guarantee.
    relationships = tuple(dict.fromkeys((*base.relationships, *head.relationships)))
    impacts = ImpactGraph(relationships).impacted(
        changed_ids,
        max_depth=request.max_impact_depth,
        min_confidence=request.min_relationship_confidence,
    )
    findings = evaluate_minimum_rules(
        head,
        minimum_room_area_sqm=request.minimum_room_area_sqm,
        minimum_door_width_mm=request.minimum_door_width_mm,
    )

    return {
        "base_revision_id": base.revision_id,
        "head_revision_id": head.revision_id,
        "changes": [asdict(change) for change in changes],
        "relationship_changes": [asdict(change) for change in relationship_changes],
        "impacts": [asdict(impact) for impact in impacts],
        "rule_findings": [asdict(finding) for finding in findings],
        "limitations": [
            "Object matching uses adapter-provided object_id values.",
            "Impact edges are candidates and retain their confidence and evidence path.",
            "Only explicitly configured deterministic rules are evaluated.",
            "This endpoint does not persist revisions or modify source design files.",
        ],
    }
