"""Deterministic design revision diffing and impact analysis.

This module is deliberately storage- and CAD-adapter-agnostic. Adapters normalize source
models into DesignSnapshot; persistence and model-specific extraction live elsewhere.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import isfinite
from typing import TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def _validate_confidence(value: float, name: str) -> None:
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be a finite number between 0 and 1")


@dataclass(frozen=True, slots=True)
class DesignObject:
    """Normalized design object extracted from a source application."""

    object_id: str
    kind: str
    properties: dict[str, JsonValue] = field(default_factory=dict)
    source_id: str | None = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.object_id.strip():
            raise ValueError("object_id must not be empty")
        if not self.kind.strip():
            raise ValueError("kind must not be empty")
        _validate_confidence(self.confidence, "confidence")


@dataclass(frozen=True, slots=True)
class Relationship:
    """Directed dependency edge: source changes may affect target."""

    source_id: str
    target_id: str
    relation_type: str
    provenance: str
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.target_id.strip():
            raise ValueError("relationship endpoints must not be empty")
        if not self.relation_type.strip():
            raise ValueError("relation_type must not be empty")
        if not self.provenance.strip():
            raise ValueError("provenance must not be empty")
        _validate_confidence(self.confidence, "confidence")


@dataclass(frozen=True, slots=True)
class DesignSnapshot:
    """Immutable revision input from a CAD/BIM adapter."""

    revision_id: str
    objects: tuple[DesignObject, ...]
    relationships: tuple[Relationship, ...] = ()

    def __post_init__(self) -> None:
        if not self.revision_id.strip():
            raise ValueError("revision_id must not be empty")
        ids = [obj.object_id for obj in self.objects]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate object_id in revision {self.revision_id!r}")
        known = set(ids)
        for edge in self.relationships:
            if edge.source_id not in known or edge.target_id not in known:
                raise ValueError(
                    "relationship endpoints must exist in the same revision: "
                    f"{edge.source_id!r} -> {edge.target_id!r}"
                )


@dataclass(frozen=True, slots=True)
class PropertyChange:
    """Before/after value for one property, preserving missing versus explicit null."""

    before: JsonValue
    after: JsonValue
    before_present: bool = True
    after_present: bool = True


@dataclass(frozen=True, slots=True)
class DesignChange:
    """Semantic change to one normalized design object."""

    object_id: str
    operation: str
    kind: str
    changed_properties: dict[str, PropertyChange] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RelationshipChange:
    """Added, removed, or updated dependency relationship."""

    operation: str
    source_id: str
    target_id: str
    relation_type: str
    provenance: str
    before_confidence: float | None
    after_confidence: float | None


@dataclass(frozen=True, slots=True)
class Impact:
    """A dependent object and the best deterministic evidence path found."""

    object_id: str
    depth: int
    path: tuple[str, ...]
    relation_types: tuple[str, ...]
    confidence: float


@dataclass(frozen=True, slots=True)
class RuleFinding:
    """Deterministic rule output with explicit evidence."""

    rule_id: str
    object_id: str
    severity: str
    message: str
    evidence: dict[str, JsonValue]


def compare_snapshots(base: DesignSnapshot, head: DesignSnapshot) -> list[DesignChange]:
    """Return a stable semantic diff between two revisions.

    Object identity is the adapter-provided object_id. Matching heuristics for unstable
    native IDs belong in adapters and must retain their own confidence/provenance.
    """
    before = {obj.object_id: obj for obj in base.objects}
    after = {obj.object_id: obj for obj in head.objects}
    changes: list[DesignChange] = []

    for object_id in sorted(before.keys() | after.keys()):
        old = before.get(object_id)
        new = after.get(object_id)
        if old is None and new is not None:
            changes.append(
                DesignChange(object_id, "added", new.kind, {})
            )
            continue
        if new is None and old is not None:
            changes.append(
                DesignChange(object_id, "removed", old.kind, {})
            )
            continue
        if old is None or new is None:
            continue

        property_names = old.properties.keys() | new.properties.keys()
        changed: dict[str, PropertyChange] = {}
        for name in sorted(property_names):
            before_present = name in old.properties
            after_present = name in new.properties
            before_value = old.properties.get(name)
            after_value = new.properties.get(name)
            if before_present != after_present or before_value != after_value:
                changed[name] = PropertyChange(
                    before=before_value,
                    after=after_value,
                    before_present=before_present,
                    after_present=after_present,
                )
        if old.kind != new.kind:
            changed["$kind"] = PropertyChange(before=old.kind, after=new.kind)
        if changed:
            changes.append(DesignChange(object_id, "updated", new.kind, changed))

    return changes


def compare_relationships(
    base: DesignSnapshot, head: DesignSnapshot
) -> list[RelationshipChange]:
    """Diff dependency edges, including changes in relationship confidence."""
    def index(snapshot: DesignSnapshot) -> dict[tuple[str, str, str, str], Relationship]:
        return {
            (edge.source_id, edge.target_id, edge.relation_type, edge.provenance): edge
            for edge in snapshot.relationships
        }

    before = index(base)
    after = index(head)
    changes: list[RelationshipChange] = []
    for key in sorted(before.keys() | after.keys()):
        old = before.get(key)
        new = after.get(key)
        if old is None and new is not None:
            changes.append(
                RelationshipChange("added", *key, before_confidence=None, after_confidence=new.confidence)
            )
        elif new is None and old is not None:
            changes.append(
                RelationshipChange("removed", *key, before_confidence=old.confidence, after_confidence=None)
            )
        elif old is not None and new is not None and old.confidence != new.confidence:
            changes.append(
                RelationshipChange(
                    "updated",
                    *key,
                    before_confidence=old.confidence,
                    after_confidence=new.confidence,
                )
            )
    return changes


class ImpactGraph:
    """Cycle-safe, bounded traversal over revision-scoped dependency edges."""

    def __init__(self, relationships: tuple[Relationship, ...]) -> None:
        adjacency: dict[str, list[Relationship]] = {}
        for edge in relationships:
            adjacency.setdefault(edge.source_id, []).append(edge)
        self._adjacency = {
            node: sorted(edges, key=lambda edge: (edge.target_id, edge.relation_type))
            for node, edges in adjacency.items()
        }

    def impacted(
        self,
        changed_ids: list[str],
        *,
        max_depth: int = 3,
        min_confidence: float = 0.0,
    ) -> list[Impact]:
        """Find dependents reachable from changed objects.

        The returned confidence is the minimum edge confidence on the selected path.
        Each object is returned once using deterministic breadth-first traversal.
        """
        if max_depth < 0:
            raise ValueError("max_depth must be >= 0")
        _validate_confidence(min_confidence, "min_confidence")

        roots = sorted(set(changed_ids))
        seen = set(roots)
        queue: deque[tuple[str, int, tuple[str, ...], tuple[str, ...], float]] = deque(
            (root, 0, (root,), (), 1.0) for root in roots
        )
        results: list[Impact] = []

        while queue:
            node, depth, path, relation_types, path_confidence = queue.popleft()
            if depth >= max_depth:
                continue
            for edge in self._adjacency.get(node, []):
                if edge.confidence < min_confidence or edge.target_id in seen:
                    continue
                seen.add(edge.target_id)
                confidence = min(path_confidence, edge.confidence)
                next_path = (*path, edge.target_id)
                next_relations = (*relation_types, edge.relation_type)
                results.append(
                    Impact(
                        object_id=edge.target_id,
                        depth=depth + 1,
                        path=next_path,
                        relation_types=next_relations,
                        confidence=confidence,
                    )
                )
                queue.append(
                    (
                        edge.target_id,
                        depth + 1,
                        next_path,
                        next_relations,
                        confidence,
                    )
                )

        return results


def evaluate_minimum_rules(
    snapshot: DesignSnapshot,
    *,
    minimum_room_area_sqm: float | None = None,
    minimum_door_width_mm: float | None = None,
) -> list[RuleFinding]:
    """Evaluate explicitly configured room-area and door-width rules.

    Thresholds are mandatory inputs when a rule is enabled; the engine does not silently
    assume jurisdictional or project requirements.
    """
    for name, threshold in (
        ("minimum_room_area_sqm", minimum_room_area_sqm),
        ("minimum_door_width_mm", minimum_door_width_mm),
    ):
        if threshold is not None and (not isfinite(threshold) or threshold < 0):
            raise ValueError(f"{name} must be a finite, non-negative number")

    findings: list[RuleFinding] = []
    for obj in sorted(snapshot.objects, key=lambda item: item.object_id):
        normalized_kind = obj.kind.casefold()
        if normalized_kind == "room" and minimum_room_area_sqm is not None:
            area = obj.properties.get("area_sqm")
            if isinstance(area, (int, float)) and not isinstance(area, bool):
                if not isfinite(float(area)):
                    continue
                if area < minimum_room_area_sqm:
                    findings.append(
                        RuleFinding(
                            rule_id="room.minimum_area",
                            object_id=obj.object_id,
                            severity="warning",
                            message="Room area is below the configured project minimum.",
                            evidence={
                                "property": "area_sqm",
                                "actual": area,
                                "threshold": minimum_room_area_sqm,
                                "unit": "m²",
                                "source_id": obj.source_id,
                                "object_confidence": obj.confidence,
                            },
                        )
                    )
        elif normalized_kind == "door" and minimum_door_width_mm is not None:
            width = obj.properties.get("width_mm")
            if isinstance(width, (int, float)) and not isinstance(width, bool):
                if not isfinite(float(width)):
                    continue
                if width < minimum_door_width_mm:
                    findings.append(
                        RuleFinding(
                            rule_id="door.minimum_width",
                            object_id=obj.object_id,
                            severity="warning",
                            message="Door width is below the configured project minimum.",
                            evidence={
                                "property": "width_mm",
                                "actual": width,
                                "threshold": minimum_door_width_mm,
                                "unit": "mm",
                                "source_id": obj.source_id,
                                "object_confidence": obj.confidence,
                            },
                        )
                    )
    return findings
