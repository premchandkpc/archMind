# Design versioning: build versus buy

## Decision

Prototype revision intelligence, not a new file-versioning engine. Reuse established storage and CAD/BIM interoperability where practical. Build ArchMind's differentiator around explainable change impact, deterministic checks, and decision memory.

## Options

| Option | Benefits | Risks | Position |
|---|---|---|---|
| Custom Rust version engine | Full control | High cost; no initial moat | Do not build first |
| Git LFS / object storage | Proven file storage | Binary diffs lack design meaning | Reuse for raw assets |
| IFC | Building-oriented objects and relationships | Export may lose native-tool details | Use for supported BIM extraction |
| USD layers | Non-destructive 3D composition | Validate AEC workflow fit | Evaluate for design options |
| Speckle | Existing connectors and object/version workflows | Platform/data-model dependency; verify current coverage and licensing | Evaluate before custom connectors |
| ArchMind impact + decision layer | Links changes to dependencies, rules, evidence and rationale | Needs quality relationships and rules | Build this |

## MVP

1. Clickable revision timeline, semantic diff and impact-review mock.
2. A small two-room IFC fixture and documented wall-change scenario.
3. Adapter contract for normalized design objects and provenance.
4. Revision-scoped dependency edges with type, provenance and confidence.
5. Deterministic rules returning inputs, thresholds, units, results and evidence.
6. AI explains verified findings and linked decisions. It must not invent reasons or present suggestions as certified structural/code approval.
7. Human review and decision-note capture.

## Domain model

- Project and design asset
- Immutable revision with parent revision and source-file hash
- Extracted object with source tool, native identifier when available, and match confidence
- Change with before/after values and units
- Revision-scoped relationship edge with type, provenance and confidence
- Rule result with rule version, inputs, outcome, severity and evidence
- Decision with source reference, author, timestamp and approval status

Native object IDs may not survive every export. Use them where reliable, with explicit fallback matching and confidence.

## Architecture boundary

- Raw files and previews: object storage.
- Revision metadata, decisions, rule results and initial relationships: PostgreSQL.
- IFC and tool adapters: normalize extracted objects while preserving provenance.
- Rule engine: deterministic, versioned code.
- LLM: explain evidence-backed findings and summarize linked decisions.
- Rust: consider only after profiling shows a hot path in hashing, diffing or geometry processing.

## Mock acceptance criteria

- Selecting a revision updates selected revision state and summary metrics.
- Selecting a base revision updates comparison labels.
- Findings can be marked reviewed or dismissed.
- A decision note requires non-empty text before a success acknowledgement.
- Responsive UI, no external runtime dependencies.
- Clearly states that data/actions are illustrative and not connected to CAD or a backend.

## Non-goals

Production CAD integrations, automatic save capture, semantic merging, concurrent editing, object locks, automated compliance approval, or a custom Git-compatible storage engine.

## Validation before production

Evaluate Speckle and IFC/IfcOpenShell on a representative sample. Measure object-match precision, changed-object recall, export fidelity, connector maintenance and architect review effort. Keep relationships in PostgreSQL until realistic traversal measurements justify a graph database.
