"""Unit tests for design revision diffing and impact analysis."""

from __future__ import annotations

import math

import pytest

from civilmind.api.routes.design_revisions import AnalyzeRevisionRequest, analyze_revision
from civilmind.design_versioning import (
    DesignObject,
    DesignSnapshot,
    ImpactGraph,
    Relationship,
    compare_relationships,
    compare_snapshots,
    evaluate_minimum_rules,
)


def test_diff_reports_added_removed_and_updated_objects() -> None:
    base = DesignSnapshot(
        revision_id="R1",
        objects=(
            DesignObject("wall-1", "wall", {"length_mm": 3000}),
            DesignObject("door-1", "door", {"width_mm": 900}),
        ),
    )
    head = DesignSnapshot(
        revision_id="R2",
        objects=(
            DesignObject("wall-1", "wall", {"length_mm": 2700}),
            DesignObject("room-1", "room", {"area_sqm": 8.5}),
        ),
    )

    changes = compare_snapshots(base, head)

    assert [(item.object_id, item.operation) for item in changes] == [
        ("door-1", "removed"),
        ("room-1", "added"),
        ("wall-1", "updated"),
    ]
    wall_change = changes[2]
    assert wall_change.changed_properties["length_mm"].before == 3000
    assert wall_change.changed_properties["length_mm"].after == 2700


def test_diff_distinguishes_missing_property_from_explicit_null() -> None:
    base = DesignSnapshot("R1", (DesignObject("wall-1", "wall", {}),))
    head = DesignSnapshot("R2", (DesignObject("wall-1", "wall", {"note": None}),))

    change = compare_snapshots(base, head)[0].changed_properties["note"]

    assert change.before is None
    assert change.after is None
    assert change.before_present is False
    assert change.after_present is True


def test_unchanged_snapshot_has_no_object_changes() -> None:
    snapshot = DesignSnapshot(
        "R1",
        (DesignObject("room-1", "room", {"area_sqm": 12.0}),),
    )

    assert compare_snapshots(snapshot, snapshot) == []


def test_duplicate_object_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate object_id"):
        DesignSnapshot(
            "R1",
            (
                DesignObject("wall-1", "wall"),
                DesignObject("wall-1", "wall"),
            ),
        )


def test_relationship_with_missing_endpoint_is_rejected() -> None:
    with pytest.raises(ValueError, match="relationship endpoints"):
        DesignSnapshot(
            "R1",
            (DesignObject("wall-1", "wall"),),
            (Relationship("wall-1", "room-1", "bounds", "ifc"),),
        )


def test_relationship_diff_includes_add_remove_and_confidence_update() -> None:
    base = DesignSnapshot(
        "R1",
        (DesignObject("wall-1", "wall"), DesignObject("room-1", "room")),
        (
            Relationship("wall-1", "room-1", "bounds", "ifc", 1.0),
        ),
    )
    head = DesignSnapshot(
        "R2",
        (DesignObject("wall-1", "wall"), DesignObject("room-1", "room")),
        (
            Relationship("wall-1", "room-1", "bounds", "ifc", 0.7),
            Relationship("wall-1", "room-1", "affects", "rule-engine", 0.9),
        ),
    )

    changes = compare_relationships(base, head)

    assert [(item.operation, item.relation_type) for item in changes] == [
        ("added", "affects"),
        ("updated", "bounds"),
    ]
    assert changes[1].before_confidence == 1.0
    assert changes[1].after_confidence == 0.7


def test_duplicate_relationships_are_rejected() -> None:
    edge = Relationship("wall-1", "room-1", "bounds", "ifc")
    with pytest.raises(ValueError, match="duplicate relationship"):
        DesignSnapshot(
            "R1",
            (DesignObject("wall-1", "wall"), DesignObject("room-1", "room")),
            (edge, edge),
        )


def test_impact_graph_is_cycle_safe_and_respects_max_depth() -> None:
    relationships = (
        Relationship("wall-1", "room-1", "bounds", "ifc"),
        Relationship("room-1", "door-1", "contains", "ifc"),
        Relationship("door-1", "wall-1", "touches", "inferred", 0.8),
    )
    graph = ImpactGraph(relationships)

    impacts = graph.impacted(["wall-1"], max_depth=2)

    assert [(item.object_id, item.depth) for item in impacts] == [
        ("room-1", 1),
        ("door-1", 2),
    ]
    assert all("wall-1" not in item.path[1:] for item in impacts)


def test_impact_graph_filters_low_confidence_edges() -> None:
    graph = ImpactGraph(
        (
            Relationship("wall-1", "room-1", "bounds", "ifc", 1.0),
            Relationship("room-1", "pipe-1", "near", "inferred", 0.4),
        )
    )

    impacts = graph.impacted(["wall-1"], max_depth=3, min_confidence=0.8)

    assert [item.object_id for item in impacts] == ["room-1"]


def test_impact_graph_rejects_invalid_depth_and_confidence() -> None:
    graph = ImpactGraph(())

    with pytest.raises(ValueError, match="max_depth"):
        graph.impacted(["wall-1"], max_depth=-1)
    with pytest.raises(ValueError, match="min_confidence"):
        graph.impacted(["wall-1"], min_confidence=math.nan)


def test_minimum_rules_return_evidence_and_do_not_assume_thresholds() -> None:
    snapshot = DesignSnapshot(
        "R1",
        (
            DesignObject("room-1", "room", {"area_sqm": 7.5}, source_id="ifc-room-1"),
            DesignObject("door-1", "door", {"width_mm": 750}, source_id="ifc-door-1"),
            DesignObject("room-2", "room", {"area_sqm": 15.0}),
        ),
    )

    assert evaluate_minimum_rules(snapshot) == []

    findings = evaluate_minimum_rules(
        snapshot,
        minimum_room_area_sqm=9.0,
        minimum_door_width_mm=800.0,
    )

    assert [item.rule_id for item in findings] == [
        "door.minimum_width",
        "room.minimum_area",
    ]
    assert findings[0].evidence["actual"] == 750
    assert findings[0].evidence["threshold"] == 800.0
    assert findings[0].evidence["source_id"] == "ifc-door-1"
    assert findings[1].evidence["unit"] == "m²"


def test_minimum_rules_reject_negative_or_non_finite_thresholds() -> None:
    snapshot = DesignSnapshot("R1", (DesignObject("room-1", "room", {"area_sqm": 10}),))

    with pytest.raises(ValueError, match="minimum_room_area_sqm"):
        evaluate_minimum_rules(snapshot, minimum_room_area_sqm=-1)
    with pytest.raises(ValueError, match="minimum_door_width_mm"):
        evaluate_minimum_rules(snapshot, minimum_door_width_mm=math.inf)


def test_rule_engine_ignores_non_numeric_area_values() -> None:
    snapshot = DesignSnapshot(
        "R1",
        (
            DesignObject("room-1", "room", {"area_sqm": "unknown"}),
            DesignObject("room-2", "room", {"area_sqm": math.nan}),
        ),
    )

    assert evaluate_minimum_rules(snapshot, minimum_room_area_sqm=10.0) == []



def test_analysis_endpoint_returns_diff_impacts_and_rule_evidence() -> None:
    request = AnalyzeRevisionRequest.model_validate(
        {
            "base": {
                "revision_id": "R1",
                "objects": [
                    {"object_id": "wall-1", "kind": "wall", "properties": {"length_mm": 3000}},
                    {"object_id": "room-1", "kind": "room", "properties": {"area_sqm": 7.5}},
                    {"object_id": "door-1", "kind": "door", "properties": {"width_mm": 750}},
                ],
                "relationships": [
                    {
                        "source_id": "wall-1",
                        "target_id": "room-1",
                        "relation_type": "bounds",
                        "provenance": "ifc",
                    },
                    {
                        "source_id": "room-1",
                        "target_id": "door-1",
                        "relation_type": "contains",
                        "provenance": "ifc",
                    },
                ],
            },
            "head": {
                "revision_id": "R2",
                "objects": [
                    {"object_id": "wall-1", "kind": "wall", "properties": {"length_mm": 2700}},
                    {"object_id": "room-1", "kind": "room", "properties": {"area_sqm": 7.5}},
                    {"object_id": "door-1", "kind": "door", "properties": {"width_mm": 750}},
                ],
                "relationships": [
                    {
                        "source_id": "wall-1",
                        "target_id": "room-1",
                        "relation_type": "bounds",
                        "provenance": "ifc",
                    },
                    {
                        "source_id": "room-1",
                        "target_id": "door-1",
                        "relation_type": "contains",
                        "provenance": "ifc",
                    },
                ],
            },
            "minimum_room_area_sqm": 9.0,
            "minimum_door_width_mm": 800.0,
        }
    )

    result = analyze_revision(request)

    assert result["base_revision_id"] == "R1"
    assert result["head_revision_id"] == "R2"
    changes = result["changes"]
    impacts = result["impacts"]
    findings = result["rule_findings"]
    assert isinstance(changes, list)
    assert isinstance(impacts, list)
    assert isinstance(findings, list)
    assert isinstance(changes[0], dict)
    assert changes[0]["object_id"] == "wall-1"
    assert [item["object_id"] for item in impacts] == ["room-1", "door-1"]
    assert [item["rule_id"] for item in findings] == [
        "door.minimum_width",
        "room.minimum_area",
    ]
