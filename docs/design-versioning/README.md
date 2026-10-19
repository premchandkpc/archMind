# ArchMind design versioning

This directory contains the first product mock and the build-versus-buy boundary for revision intelligence.

- [Interactive revision mock](./mock.html): open this static page in a browser. It uses illustrative data and local interactions only.
- [Build-versus-buy and MVP decision](./build-vs-buy.md): product boundary, data model, risks, and acceptance criteria.

## Preview locally

Open `mock.html` directly in a browser. No package installation, API keys, or build step is required.

## Important limitation

The mock is not connected to CAD files, IFC parsing, persistent storage, or an approval backend. Its geometry and review findings are illustrative. Do not treat its output as design, code-compliance, or structural approval.

## First implementation slice

The branch now includes a stateless semantic-analysis endpoint at `POST /design-revisions/analyze`.

It accepts normalized `base` and `head` snapshots with object properties and directed dependency relationships, then returns:
- added, removed, and updated objects with before/after values;
- added, removed, or confidence-updated relationships;
- bounded, cycle-safe impact candidates with evidence paths and confidence;
- optional configured minimum room-area and door-width findings with units and evidence.

Example request (abbreviated):

```json
{
  "base": {
    "revision_id": "R1",
    "objects": [
      {"object_id": "wall-1", "kind": "wall", "properties": {"length_mm": 3000}},
      {"object_id": "room-1", "kind": "room", "properties": {"area_sqm": 8.0}}
    ],
    "relationships": [
      {
        "source_id": "wall-1",
        "target_id": "room-1",
        "relation_type": "bounds",
        "provenance": "ifc",
        "confidence": 1.0
      }
    ]
  },
  "head": {
    "revision_id": "R2",
    "objects": [
      {"object_id": "wall-1", "kind": "wall", "properties": {"length_mm": 2700}},
      {"object_id": "room-1", "kind": "room", "properties": {"area_sqm": 7.5}}
    ],
    "relationships": [
      {
        "source_id": "wall-1",
        "target_id": "room-1",
        "relation_type": "bounds",
        "provenance": "ifc",
        "confidence": 1.0
      }
    ]
  },
  "minimum_room_area_sqm": 9.0,
  "max_impact_depth": 3,
  "min_relationship_confidence": 0.7
}
```

The endpoint is deliberately stateless: it does not persist revisions, read native CAD files, or modify design assets. Adapter-generated object IDs and relationship provenance are inputs, not claims that matching is universally reliable. Thresholds must be supplied by the project; the service does not invent jurisdictional requirements.
