# Architecture Flows — Phases 1–9

## Diagram legend

```
[File:path]         → File involved
class/method()      → Class and method
{data}              → Example data passed between steps
Redis Stream:name   → Event bus stream
```

---

## 1. Startup

```
[api/app.py]
  lifespan()
    → creates EventBus(redis_url)            → [events/bus.py:148]
    → stores as app.state.event_bus
    → creates PipelineWorker(bus, "worker-1") → [events/workers.py:58]
    → asyncio.create_task(worker.run())       → background consumer loop
    → registers routes: health, upload

Worker.run() loop:
  -> EventConsumer.consume("ingestion", "pipeline-workers", "worker-1")
  -> on event: route to handler_by_event_type["document.uploaded"]
  -> handle_document_uploaded(event, parser, chunker, bus)
```

---

## 2. Upload → Parse

### Entry

```
POST /upload                    → [api/routes/upload.py:24] upload_file()
  Headers: Content-Type: multipart/form-data
  Body:
    file: <binary>              → supports {.pdf,.docx,.xlsx,.png,.jpg,.jpeg}
    project_id: "proj-101"

Validation:
  → checks suffix in SUPPORTED_FORMATS = {.pdf, .docx, .xlsx, .png, .jpg, .jpeg}
  → checks file size ≤ 100MB

Saves to disk:
  path: uploads/proj-101/docs/{doc_id}.pdf
  doc_id = uuid4 (e.g. "a1b2c3d4-...")
```

### Event published

```json
{
  "event_type": "document.uploaded",
  "document_id": "a1b2c3d4-e5f6-...",
  "project_id": "proj-101",
  "file_path": "uploads/proj-101/docs/a1b2c3d4-e5f6-....pdf",
  "filename": "foundation_plan.pdf"
}
```

Response: `202 Accepted` with `{"document_id": ..., "filename": ..., "file_type": ..., "file_size": ..., "storage_path": "uploads/{project_id}/docs/{doc_id}{ext}", "status": "processing"}`

### Worker picks up

```
PipelineWorker._get_handler("document.uploaded")
  → handle_document_uploaded(event, parser, chunker, bus)  → [events/handlers.py:27]

  Calls: parser.parse("uploads/proj-101/docs/a1b2c3d4-....pdf")
         → [pipeline/parser.py:79] DocumentParser._parse_pdf()

  Unstructured.partition_pdf(strategy="hi_res"):
    Returns list of elements classified by type(element).__name__:
      Title        → ElementType.TITLE
      NarrativeText → ElementType.NARRATIVE
      Table        → ElementType.TABLE
      Image        → ElementType.IMAGE
      ListItem     → ElementType.LIST
      PageBreak    → ElementType.PAGE_BREAK (skipped)
    Fallback → if Unstructured fails, PaddleOCR via _fallback_ocr_pdf()
```

### ParsedElement example

```python
ParsedElement(
    type=ElementType.TITLE,
    content="Foundation Details",
    page_number=3,
    metadata={"element_index": 2, "char_count": 18},
)

ParsedElement(
    type=ElementType.NARRATIVE,
    content="M25 concrete grade is used for all foundation works...",
    page_number=3,
    metadata={"element_index": 3, "char_count": 142},
)

ParsedElement(
    type=ElementType.TABLE,
    content="",
    table_data=[
        ["Item", "Spec", "Quantity"],
        ["Concrete", "M25", "50 cum"],
        ["Steel", "Fe500", "2000 kg"],
    ],
    page_number=4,
    metadata={"element_index": 5, "char_count": 0},
)

ParsedElement(
    type=ElementType.IMAGE,
    content="[Image: foundation_plan.png]",
    image_path="/tmp/civilmind_images/img_001.png",
    page_number=5,
)
```

### Next event

```json
{
  "event_type": "document.parsed",
  "document_id": "a1b2c3d4-...",
  "project_id": "proj-101",
  "elements": [
    {"type": "title", "content": "Foundation Details", "page_number": 3, ...},
    {"type": "narrative", "content": "M25 concrete grade...", ...},
    {"type": "table", "content": "", "table_data": [["Item","Spec","Quantity"],...], ...},
    {"type": "image", "content": "[Image: ...]", "image_path": "/tmp/...", ...}
  ]
}
```

---

## 3. Parse → Chunk

```
handle_document_parsed(event, chunker, bus)  → [events/handlers.py:66]

  Reconstructs: list[ParsedElement] from event["elements"]

  Calls: chunker.chunk(elements, document_id, project_id)
         → [pipeline/chunker.py:57]

  Chunker.__init__(chunk_size=1000, chunk_overlap=200, use_semantic=False)

  Per element:
    TITLE  → flush_buffer(), set current_section = "Foundation Details"
    NARRATIVE → accumulate into text_buffer
    TABLE  → flush_buffer(), _chunk_from_table() → markdown
    IMAGE  → flush_buffer(), _chunk_from_image() → stub chunk
    PAGE_BREAK → skip
    When buffer ≥ 1000 chars → flush via _fixed_split(text, meta)

  Metadata extracted via:
    extract_metadata(text) → [pipeline/metadata.py:85]
      → measurements: ["M25", "50 cum", "2000 kg"]
      → code_references: []
      → keywords: {"concrete", "steel", "foundation"}
      → is_technical: True
```

### Chunks produced

```python
Chunk(
    id="chunk-aaa",
    content="Foundation Details M25 concrete grade is used for all foundation works...",
    metadata={
        "document_id": "a1b2c3d4-...",
        "project_id": "proj-101",
        "section": "Foundation Details",
        "chunk_type": "text",
        "page_number": 3,
        "char_count": 850,
        "word_count": 142,
        "has_measurements": True,
        "measurements": ["M25"],
        "has_code_references": False,
        "code_references": [],
        "is_technical": True,
    }
)

Chunk(
    id="chunk-bbb",
    content="| Item | Spec | Quantity |\n|---|---|---|\n| Concrete | M25 | 50 cum |\n| Steel | Fe500 | 2000 kg |",
    metadata={
        "document_id": "a1b2c3d4-...",
        "project_id": "proj-101",
        "section": "Foundation Details",
        "chunk_type": "table",
        "page_number": 4,
        "char_count": 98,
        "word_count": 14,
        "has_measurements": True,
        "measurements": ["M25", "50 cum", "2000 kg"],
        "is_technical": True,
    }
)

Chunk(
    id="chunk-ccc",
    content="[Image: foundation_plan.png]",
    metadata={
        "document_id": "a1b2c3d4-...",
        "project_id": "proj-101",
        "section": "Foundation Details",
        "chunk_type": "image",
        "image_path": "/tmp/civilmind_images/img_001.png",
        "page_number": 5,
    }
)
```

### Next event

```json
{
  "event_type": "document.chunked",
  "document_id": "a1b2c3d4-...",
  "project_id": "proj-101",
  "chunks": [
    {"id": "chunk-aaa", "content": "...", "metadata": {...}},
    {"id": "chunk-bbb", "content": "...", "metadata": {...}},
    {"id": "chunk-ccc", "content": "...", "metadata": {...}}
  ]
}
```

---

## 4. Chunk → Embed → Index

```
handle_document_chunked(event, embedder, store, bus)  → [events/handlers.py:106]

  Calls: embedder.embed_batch(["Foundation Details M25...", "| Item | Spec |...", "[Image: ...]"])
         → [pipeline/embedder.py]

  EmbedderFactory.create(provider="bge") → CachedEmbedder(BGEEmbedder("BAAI/bge-base-en-v1.5"))

    BGEEmbedder.embed_batch():
      model.encode([...], normalize_embeddings=True)
      → [[0.023, -0.014, ..., 0.087], [...], [...]]  (3 × 768-dim vectors)

    CachedEmbedder:
      SHA256(content) → checks ~/.cache/civilmind/embeddings/{hash}.npy
      if miss: compute + save as .npy

  Calls: store.upsert(collection="civilmind", vectors=[...], payloads=[...])
         → [vector/qdrant_store.py:62] QdrantStore.upsert()

    Qdrant PointStruct:
      id = uuid4 (point_id)
      vector = [0.023, -0.014, ...] (768 floats)
      payload = {document_id, project_id, section, chunk_type, ...}

    Returns: ["point-111", "point-222", "point-333"]
```

### Next event

```json
{
  "event_type": "document.embedded",
  "document_id": "a1b2c3d4-...",
  "project_id": "proj-101",
  "chunks": [
    {"id": "chunk-aaa", "content": "...", "metadata": {...}, "embedding_id": "point-111"},
    {"id": "chunk-bbb", "content": "...", "metadata": {...}, "embedding_id": "point-222"},
    {"id": "chunk-ccc", "content": "...", "metadata": {...}, "embedding_id": "point-333"}
  ]
}
```

### Final step

```
handle_document_embedded(event, bus)  → [events/handlers.py:156]

  → publish "document.indexed"
```

```json
{
  "event_type": "document.indexed",
  "document_id": "a1b2c3d4-...",
  "project_id": "proj-101",
  "chunk_count": 3
}
```

---

## 5. Query (existing Phase 2 tools)

### Vector search

```
Tool: VectorSearchTool → [tools/vector_search.py]
  execute(query_vector=[0.023, ...], project_id="proj-101", top_k=5)

  → QdrantStore.search(collection="civilmind", query_vector=[...], limit=5)
  → [vector/qdrant_store.py:82]

  _client.query_points(collection_name="civilmind", query=[...], limit=5)
  → [
      SearchResult(id="point-111", score=0.89, payload={...}),
      SearchResult(id="point-222", score=0.76, payload={...}),
    ]
```

### SQL query

```
Tool: SQLQueryTool → [tools/sql_query.py]
  execute(query="SELECT * FROM documents WHERE project_id = 'proj-101'")

  Read-only guard: rejects INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE
  → asyncpg.connect(command_timeout=5)
  → Returns: [{"id": "doc-1", "filename": "foundation_plan.pdf", ...}]
```

### OCR

```
Tool: OCRTool → [tools/ocr.py]
  execute(image_path="/tmp/civilmind_images/img_001.png")

  → PaddleOCR lazy-load → engine.ocr(path, cls=True)
  → Returns: [
      {"text": "Foundation Plan", "confidence": 0.95, "bbox": [[x1,y1],[x2,y2],...]},
      {"text": "Scale 1:100", "confidence": 0.88, "bbox": [...]},
    ]
```

### Vision LLM

```
Tool: VisionLLMTool → [tools/vision_llm.py]
  execute(image_path="img_001.png", prompt="Describe this architectural drawing")

  → LLMClient(settings.llm_vision_config).vision(img_base64, mime_type, prompt)
  → [llm/client.py:90]

  OpenAI-compatible:
    POST {base_url}/chat/completions
    Body: {model, messages: [{role: "user", content: [{type: "text"}, {type: "image_url"}]}]}
  Anthropic native:
    POST anthropic_api_url
    Body: {model, messages: [{role: "user", content: [{type: "image", source: {base64}}, {type: "text"}]}]}

  Returns: LLMResult(content="This is a foundation plan showing...", model="gpt-5", ...)
```

### Calculator

```
Tool: CalculatorTool → [tools/calculator.py]
  execute(expression="2 * pi * 5 ^ 2")

  → AST safe eval (no eval()):
    parses ast → whitelist: {Add, Sub, Mult, Div, Pow, pi, e, sin, cos, tan, log, sqrt}
    blocks: __import__, os, system, exec, compile, getattr, setattr
  → Returns: 157.07963267948966
```

### Code search

```
Tool: CodeSearchTool → [tools/code_search.py]
  execute(query="concrete grade for beams", code="IS456", section="5.3")

  → In-memory building code database:
    IBC, ACI, ASCE, IECC indexed by keywords
  → Returns: [
      {"code": "IS 456", "section": "5.3", "content": "Minimum concrete grade M20 for reinforced concrete...", "relevance": 0.92},
    ]
```

---

## 6. Hybrid Retrieval (Phase 4)

### BM25 + Vector Search

```
HybridRetriever.retrieve(query, project_id)  → [retrieval/hybrid.py]

  1. BM25 keyword search:
     BM25Index.search(query, top_k=20)  → [retrieval/bm25_index.py]
       → tokenizes query, scores against inverted index
       → returns list[BM25Result(id, score)]

  2. Vector semantic search:
     VectorSearchTool.execute(query_vector, project_id, top_k=20)
       → QdrantStore.search(collection="civilmind", query_vector=[...], limit=20)
       → returns list[SearchResult(id, score, payload)]

  3. RRF merge:
     reciprocal_rank_fusion bm25_results + vector_results
       → score = Σ 1/(k + rank_i)  (k=60)
       → merges duplicates, returns top 30

  4. Rerank:
     CrossEncoderReranker.rerank(query, merged_chunks, top_k=10)
       → sentence-transformers CrossEncoder model
       → scores each (query, chunk) pair
       → returns top 10 by relevance

  Returns: list[RetrievedChunk] with id, content, score, source, metadata
```

---

## 7. Workflow Graph (Phase 5)

### LangGraph State Flow

```
START → planner → router
                    |
        +-----------+-----------+-----------+
        |           |           |           |
    retriever  estimator  compliance  analysis_crew
        |           |           |       (CrewAI)
        +-----------+-----------+-----------+
                    |
                  reviewer
                    |
            +-------+-------+
            |               |
         reporter      planner (loop back if issues)
            |
           END
```

### State Model

```
ProjectState (TypedDict)  → [workflow/state.py]
  Input:     project_id, question, document_ids
  Retrieval: retrieved_chunks (Annotated[add_messages])
  Analysis:  drawing_analysis, violations, cost_estimation, schedule, risk_assessment
  CrewAI:    analysis_result (text output from CrewAI crew execution)
  Review:    review_feedback
  Output:    final_answer
  Control:   messages, iteration, needs_human_approval, current_node, next_nodes
  Memory:    context (dict)
```

### Node Execution

```
planner_node(state)  → [workflow/nodes.py:48]
  LLM call → analyzes question, returns tasks + required_nodes
  → sets next_nodes for routing

retriever_node(state)  → [workflow/nodes.py:79]
  Will use HybridRetriever (Phase 4)
  → returns retrieved_chunks

compliance_node(state)  → [workflow/nodes.py:113]
  LLM call → checks building codes against retrieved context
  → returns violations

estimator_node(state)  → [workflow/nodes.py:148]
  LLM call → calculates quantities and costs
  → returns cost_estimation

reviewer_node(state)  → [workflow/nodes.py:245]
  Checks: chunks exist, confidence > 0.5, no critical violations
  → if issues + iteration < 3: loop back to planner
  → else: proceed to reporter

reporter_node(state)  → [workflow/nodes.py:300]
  LLM call → generates final markdown report
  → sets final_answer
```

### Routing Logic

```
route_after_planner(state)  → [workflow/graph.py:45]
  Maps planner output to node names:
    "retrieval" → "retriever"
    "estimation" → "estimator"
    "compliance_check" → "compliance"
    "complex_analysis" → "analysis_crew" (CrewAI delegation)
    "drawing_analysis" → "drawing_analyzer"
    "scheduling" → "scheduler"
    "risk_analysis" → "risk_analyzer"
  → picks first node from list

route_after_review(state)  → [workflow/graph.py:61]
  if review_feedback.is_valid → "reporter"
  if iteration < MAX_ITERATIONS → "planner" (loop)
  else → "reporter" (force exit)
```

---

## 8. Agent Definitions (Phase 6)

### CrewAI Agent Architecture

```
AgentFactory  → [agents/roles.py]
  Creates 9 specialized agents:
    planner, retriever, drawing_analyzer, compliance,
    estimator, scheduler, risk_analyzer, reviewer, report_writer

Each agent has:
  - role: Human-readable name
  - goal: What the agent tries to accomplish
  - backstory: Domain expertise context
  - tools: CrewAI tool wrappers bridging to project tools
  - llm: LLM instance (openai/{LLM_CHAT_MODEL})
```

### Tool Wrappers

```
CrewAI tools  → [agents/tools.py]
  VectorSearchTool   → wraps civilmind.tools.vector_search
  SQLQueryTool       → wraps civilmind.tools.sql_query
  CalculatorTool     → wraps civilmind.tools.calculator
  OCRTool            → wraps civilmind.tools.ocr
  VisionLLMTool      → wraps civilmind.tools.vision_llm
  CodeSearchTool     → wraps civilmind.tools.code_search
  WeatherAPITool     → stub implementation

Pattern: CrewAI _run() → asyncio.run(project_tool.execute()) → str
```

### Crew Orchestration

```
CivilMindCrew  → [agents/crew.py]
  __init__(project_id, question, retrieved_chunks, document_ids, tools)
    → AgentFactory.create_all() → 9 agents
    → _create_tasks() → 8 tasks (retriever → report_writer)

  run() → CrewResult
    → Crew.kickoff() with Process.hierarchical
    → Memory enabled (long-term, short-term, entity)
    → Returns CrewResult(analysis, chunks, violations, cost_estimate, schedule, risks)

CrewResult  → [agents/crew.py]
  Structured result returned to LangGraph state machine
  → analysis: str (full text output)
  → violations, cost_estimate, schedule, risks: extracted data
```

### Hybrid Integration (LangGraph + CrewAI)

```
analysis_crew_node(state)  → [workflow/nodes.py:345]
  Called when planner routes to "complex_analysis"
  → Creates CivilMindCrew with LangGraph state context
  → Runs CrewAI in thread pool (asyncio.to_thread)
  → Returns partial state update with analysis_result + extracted data

Flow: planner → route_after_planner → analysis_crew_node → CrewAI → reviewer
```

### Execution Flow

```
CivilMindCrew.run()
  │
  ├─→ Planner Agent
  │     └─ Creates task list, delegates
  │
  ├─→ Manager (LLM)
  │     └─ Decides which agent runs next
  │
  ├─→ Retriever Agent
  │     └─ Searches documents (vector_search + sql_query)
  │
  ├─→ Drawing Analyzer
  │     └─ Analyzes floor plans (vision_llm + ocr)
  │
  ├─→ Compliance Agent
  │     └─ Checks building codes (code_search)
  │
  ├─→ Estimator Agent
  │     └─ Calculates quantities (calculator + sql_query)
  │
  ├─→ Scheduler Agent
  │     └─ Creates timeline (calculator)
  │
  ├─→ Risk Analyzer
  │     └─ Identifies risks (weather_api)
  │
  ├─→ Reviewer Agent
  │     └─ Validates outputs (calculator)
  │
  └─→ Report Writer
        └─ Generates final report
```

---

## 9. Vision Processing (Phase 7)

### OCR Engine

```
OCREngine  → [vision/ocr.py]
  __init__(lang="en")
    → lazy-load PaddleOCR

  extract_text(image_path) → list[OCRResult]
    → PaddleOCR.ocr(path, cls=True)
    → returns: [OCRResult(text, confidence, bbox)]

  extract_all_text(image_path) → str
    → joins all OCRResult.text
```

### Floor Plan Analysis

```
FloorPlanAnalyzer  → [vision/floorplan.py]
  __init__(model=settings.LLM_VISION_MODEL)

  analyze(image_path) → DrawingAnalysis
    → base64-encode image
    → POST {base_url}/chat/completions with vision model
    → prompt: extract rooms, walls, doors, windows, columns, beams
    → returns DrawingAnalysis(drawing_type, rooms, walls, columns, beams, ...)

  analyze_batch(image_paths) → list[DrawingAnalysis]
    → asyncio.gather() for parallel analysis
```

### Table Extraction

```
TableExtractor  → [vision/tables.py]
  __init__(vision_model=...)

  extract_from_pdf(pdf_path) → list[ExtractedTable]
    → pdfplumber.open(pdf_path) → page.extract_tables()
    → classify_table(headers) → TableType.BOQ|SPEC|SCHEDULE|UNKNOWN
    → returns list of ExtractedTable

  extract_from_image(image_path) → list[ExtractedTable]
    → vision LLM prompt: "Extract all tables as JSON"
    → classify headers → returns list of ExtractedTable

  to_boq_json(table) → {items: [...], total: float, currency: "INR"}
    → converts BOQ table to structured JSON
```

---

## 10. Knowledge Graph (Phase 8)

### Graph Schema

```
[civilmind/graph/schema.py]
  12 Node Labels:
    Project, Building, Floor, Room, Wall, Column,
    Beam, Door, Window, Material, Vendor, BuildingCode

  12 Relationship Types:
    HAS_BUILDING, HAS_FLOOR, HAS_ROOM, HAS_WALL, HAS_COLUMN,
    HAS_DOOR, HAS_WINDOW, SUPPORTS, USES_MATERIAL, SUPPLIED_BY,
    FOLLOWS_CODE, REFERENCES

  VALID_EDGES: 12 (label, rel_type, label) tuples
    Project --HAS_BUILDING--> Building
    Building --HAS_FLOOR--> Floor
    Floor --HAS_ROOM--> Room
    Room --HAS_WALL--> Wall
    Wall --HAS_DOOR--> Door / Wall --HAS_WINDOW--> Window
    Floor --HAS_COLUMN--> Column
    Column --SUPPORTS--> Beam
    Beam --USES_MATERIAL--> Material / Wall --USES_MATERIAL--> Material
    Material --SUPPLIED_BY--> Vendor
    Building --FOLLOWS_CODE--> BuildingCode

  CONSTRAINT_QUERIES: CREATE CONSTRAINT IF NOT EXISTS FOR (n:Label) REQUIRE n.id IS UNIQUE

  Dataclasses:
    GraphEntity(label, properties)      — validates label in NODE_LABELS, requires "id"
    GraphRelationship(from_id, to_id, rel_type, properties) — validates rel_type in RELATIONSHIP_TYPES
```

### Entity Extraction

```
EntityExtractor  → [civilmind/graph/entities.py:64]
  extract_from_text(text, project_id, document_id) → ExtractionResult
    → MATERIAL_PATTERNS regex scan:
        \bM\d{1,3}\b → "Concrete" (grade=M25)
        \bFe\s?\d{2,3}\b → "Steel" (grade=Fe500)
        \bbrick\b, \bmortar\b, \btile\b, \bpipe\b, ...
    → CODE_PATTERNS regex scan:
        \bIS\s?\d{3,4}\b → "IS" (e.g., IS 456)
        \bNBC\s?\d{0,4}\b → "NBC"
        \bACI\s?\d[\d-]*\b → "ACI"
    → Returns: list[ExtractedEntity(label, name, properties)]

  extract_from_drawing_analysis(analysis, project_id, document_id) → ExtractionResult
    → Takes DrawingAnalysis JSON from FloorPlanAnalyzer
    → Creates entity hierarchy:
        Project → Building → Floor → Room(s)
                          → Column(s)
                          → Beam(s)
                          → Wall(s)
                          → Door(s)
                          → Window(s)
    → Creates relationships:
        HAS_BUILDING, HAS_FLOOR, HAS_ROOM, HAS_COLUMN, etc.
    → Returns: ExtractionResult(entities, relationships)
```

### Neo4j Store

```
Neo4jStore  → [civilmind/graph/neo4j_store.py:23]
  __init__(uri, user, password)
    → lazy-load neo4j.AsyncGraphDatabase

  create_constraints()
    → runs CONSTRAINT_QUERIES (12 unique ID constraints)

  create_entity(entity: GraphEntity) → str
    → MERGE (n:Label {id: $id}) SET n += $props RETURN n.id
    → idempotent: updates on conflict

  create_relationship(rel: GraphRelationship) → None
    → MATCH (a {id: $from_id}), (b {id: $to_id})
    → MERGE (a)-[r:REL_TYPE]->(b) SET r += $props

  create_entities_batch(entities, relationships) → int
    → sequential MERGE for each entity + relationship
    → returns entity count

  traverse(start_id, relationship, max_depth, direction) → list[dict]
    → MATCH path = (start {id: $id})-[r]->(end)
    → WHERE type(r) = $rel_type AND length(path) <= $max_depth
    → Returns end nodes with depth + rel_types

  query(cypher, params) → list[dict]
    → arbitrary Cypher execution

  delete_project(project_id) → int
    → MATCH (n {project_id: $id}) DETACH DELETE n
    → returns count of deleted nodes

  health_check() → bool
    → driver.verify_connectivity()
```

### Graph Traversal

```
GraphTraversal  → [civilmind/graph/traversal.py:54]
  __init__(store: Neo4jStore)

  find_paths(start_label, start_name, project_id, max_depth) → TraversalResult
    → finds start node by label + name
    → traverses outward with empty relationship type (any edge)
    → direction="both"
    → returns GraphPath(nodes, relationships, length)

  find_material_chain(room_name, project_id) → TraversalResult
    → hardcoded Cypher: Room→Wall→Material→Vendor
    → "What vendor supplies concrete for Bedroom 1?"
    → returns 4-node path: Room --HAS_WALL--> Wall --USES_MATERIAL--> Material --SUPPLIED_BY--> Vendor

  find_building_codes(entity_name, project_id) → TraversalResult
    → Building --FOLLOWS_CODE--> BuildingCode
    → "Which codes apply to this building?"

  get_full_context(project_id, max_nodes) → TraversalResult
    → MATCH (n {project_id: $id}) — all project entities
    → MATCH (a {project_id})-[r]->(b {project_id}) — all project relationships
    → returns full graph for context building

  TraversalResult:
    paths: list[GraphPath]        — discovered paths
    entities: list[dict]           — reached entity nodes
    relationships: list[dict]      — (from_id, rel_type, to_id) triples
    .evidence → list[str]          — human-readable path summaries
```

### GraphRAG Pipeline

```
GraphRAG  → [civilmind/graph/graphrag.py:70]
  __init__(neo4j, vector_store, embedder, llm)

  retrieve(query, project_id, top_k) → GraphContext
    Step 1: Vector search
      → embedder.embed(query) → query_vector
      → vector_store.search(collection, query_vector, filter=project_id, limit=top_k)
      → context.vector_chunks = [{id, content, source, score}, ...]

    Step 2: Entity hint extraction
      → _extract_entity_hints(query, chunks) → list[(label, name)]
      → regex: \bM\d{1,3}\b → ("Material", "M25")
      → regex: \b(bedroom|kitchen|...)\b → ("Room", "Bedroom")
      → regex: \b(IS|ACI)\s?\d+ → ("BuildingCode", "IS 456")

    Step 3: Graph traversal per hint
      → traversal.find_paths(label, name, project_id, max_depth=2)
      → collect unique entities + relationships + evidence

    Step 4: Merge into GraphContext
      → context.vector_chunks + graph_entities + graph_relationships + evidence

  answer(query, project_id) → str
    → retrieve() → GraphContext
    → context.to_prompt() → formatted prompt section
    → LLM.chat(prompt) → answer string

  GraphContext.to_prompt() → str
    → "## Relevant Document Excerpts" (top 5 chunks, 500 chars each)
    → "## Knowledge Graph Entities" (top 20 entities)
    → "## Graph Relationships" (top 15 relationships as src --[type]--> tgt)
    → "## Supporting Evidence" (path summaries)
```

### Workflow Checkpoint

```
PostgresSaver  → [civilmind/workflow/checkpoint.py:17]
  __init__(dsn: str)

  setup() → None
    → CREATE TABLE workflow_checkpoints (
        thread_id TEXT, checkpoint_id TEXT,
        parent_checkpoint_id TEXT,
        checkpoint JSONB, metadata JSONB,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (thread_id, checkpoint_id)
      )
    → CREATE INDEX idx_checkpoints_thread ON (thread_id, created_at DESC)

  save(thread_id, checkpoint_id, state, metadata, parent_checkpoint_id) → None
    → INSERT ... ON CONFLICT DO UPDATE

  load(thread_id, checkpoint_id) → dict | None
    → if checkpoint_id: fetch specific
    → else: ORDER BY created_at DESC LIMIT 1

  list_checkpoints(thread_id, limit) → list[dict]
    → returns summaries without full state

  delete_thread(thread_id) → int
    → DELETE ... RETURN count
```

---

## 11. Evaluation (Phase 9)

### Retrieval Metrics

```
RetrievalMetrics  → [civilmind/evaluation/metrics.py]
  __init__(k=5)

  evaluate(query_results) → RetrievalMetricResult
    query_results: list[{retrieved_ids: list[str], relevant_ids: set[str]}]

    Per-query metrics:
      Recall@K    = |retrieved ∩ relevant| / |relevant|
      Precision@K = |retrieved ∩ relevant| / K
      MRR         = 1 / rank_of_first_relevant
      NDCG@K      = DCG / IDCG  (DCG = Σ 1/log2(rank+2))
      Hit Rate    = 1 if any relevant in top K, else 0

    Aggregated: mean across all queries
    Returns: RetrievalMetricResult(recall, precision, mrr, ndcg, hit_rate, total, k)
```

### Faithfulness Checker

```
FaithfulnessChecker  → [civilmind/evaluation/faithfulness.py]
  __init__(llm: LLMClient, threshold=0.7)

  evaluate(query, context, answer) → FaithfulnessResult
    → LLM-as-judge prompt with system role "strict evaluation judge"
    → Returns JSON: {faithfulness_score, relevance_score, completeness_score,
                      overall_score, hallucinated_claims, missing_aspects, explanation}
    → Parses markdown-fenced JSON responses
    → .is_faithful = faithfulness_score >= threshold

  batch_evaluate(evaluations) → list[FaithfulnessResult]
    → Sequential evaluation of multiple (query, context, answer) triples
```

### Cost Tracker

```
CostTracker  → [civilmind/evaluation/cost_tracker.py]
  __init__(cost_per_1m: dict | None)
    → default rates: gpt-5 $2.50/M, gpt-4o-mini $0.15/M, claude-sonnet $3.00/M

  record(query_id, model, input_tokens, output_tokens, ...) → QueryCost
    → cost_usd = (total_tokens / 1M) * rate

  record_from_llm_result(query_id, model, tokens_used, ...) → QueryCost
    → convenience wrapper for LLMResult objects

  Properties:
    .total_cost   → sum of all costs
    .total_tokens → sum of all tokens
    .query_count  → number of records
    .avg_latency_ms → mean latency

  Aggregation:
    .by_model()    → {model: {count, tokens, cost_usd}}
    .by_operation() → {operation: {count, tokens, cost_usd}}
    .summary()     → full cost report dict
```

### Benchmark Runner

```
BenchmarkRunner  → [civilmind/evaluation/benchmarks.py]
  __init__(retriever, faithfulness_checker, retrieval_metrics, cost_tracker)

  run(cases, project_id) → BenchmarkReport
    For each BenchmarkCase:
      → retriever.retrieve(query, project_id) → retrieved_ids
      → RetrievalMetrics.evaluate([{retrieved_ids, relevant_ids}])
      → FaithfulnessChecker.evaluate(query, context, answer) [if checker available]
      → BenchmarkResult(query, retrieval_metrics, faithfulness, latency, passed)

    Aggregated:
      → BenchmarkReport(total, passed, failed, avg_retrieval, avg_faithfulness, cost)

  load_cases(path) → list[BenchmarkCase]
    → JSON format: [{query, relevant_ids, context, expected_answer, tags}]

  save_report(report, path)
    → Serializes BenchmarkReport to JSON
```

---

## File inventory (Phases 1-9)

### Phase 1 — Foundation

| File | Key exports |
|------|-------------|
| `civilmind/settings.py` | `Settings` class with all env vars, `settings` singleton |
| `civilmind/config.py` | `CHUNK_SIZE`, `BM25_TOP_K`, `DEFAULT_COLLECTION`, etc. |
| `civilmind/api/app.py` | `create_app()`, `app` (main entry: `civilmind.api.app:app`) |
| `civilmind/api/routes/health.py` | `GET /health` — checks all 5 services |
| `civilmind/api/routes/upload.py` | `POST /upload` — file validation, save, publish event |
| `civilmind/db/models.py` | SQLAlchemy: `Project`, `Document`, `Chunk` |
| `civilmind/vector/qdrant_store.py` | `QdrantStore` — create, upsert, search, scroll, delete |
| `civilmind/storage/minio_client.py` | `MinIOStorage` — upload, download, list, delete |
| `civilmind/events/bus.py` | `EventBus`, `EventPublisher`, `EventConsumer` |

### Phase 2 — Tools

| File | Key exports |
|------|-------------|
| `civilmind/tools/base.py` | `BaseTool`, `ToolResult` |
| `civilmind/tools/vector_search.py` | `VectorSearchTool` |
| `civilmind/tools/sql_query.py` | `SQLQueryTool` |
| `civilmind/tools/vision_llm.py` | `VisionLLMTool` |
| `civilmind/tools/ocr.py` | `OCRTool` |
| `civilmind/tools/calculator.py` | `CalculatorTool` |
| `civilmind/tools/code_search.py` | `CodeSearchTool` |
| `civilmind/llm/client.py` | `LLMClient`, `LLMConfig`, `LLMProvider` |

### Phase 3 — Pipeline

| File | Key exports |
|------|-------------|
| `civilmind/pipeline/parser.py` | `DocumentParser`, `ParsedElement`, `ElementType` |
| `civilmind/pipeline/metadata.py` | `extract_metadata()`, `TextMetadata` |
| `civilmind/pipeline/chunker.py` | `Chunker`, `Chunk` |
| `civilmind/pipeline/embedder.py` | `EmbedderFactory`, `BaseEmbedder`, `CachedEmbedder`, `BGEEmbedder`, `OpenCodeEmbedder` |
| `civilmind/events/handlers.py` | `handle_document_uploaded`, `handle_document_parsed`, `handle_document_chunked`, `handle_document_embedded` |
| `civilmind/events/workers.py` | `PipelineWorker` |

### Phase 4 — Retrieval

| File | Key exports |
|------|-------------|
| `civilmind/retrieval/bm25_index.py` | `BM25Index`, `BM25Result` |
| `civilmind/retrieval/hybrid.py` | `HybridRetriever`, `retrieve()` |
| `civilmind/retrieval/reranker.py` | `CrossEncoderReranker`, `rerank()` |
| `civilmind/retrieval/compressor.py` | `ContextCompressor` |

### Phase 5 — Workflow

| File | Key exports |
|------|-------------|
| `civilmind/workflow/state.py` | `ProjectState`, `create_initial_state()`, 7 helper TypedDicts |
| `civilmind/workflow/nodes.py` | 10 node functions, `NODE_REGISTRY`, `set_llm()` |
| `civilmind/workflow/graph.py` | `build_graph()`, `route_after_planner()`, `route_after_review()` |
| `civilmind/workflow/checkpoint.py` | `PostgresSaver` — save, load, list, delete workflow checkpoints |

### Phase 6 — Agents

| File | Key exports |
|------|-------------|
| `civilmind/agents/roles.py` | `AgentFactory`, 9 create_*() methods |
| `civilmind/agents/tools.py` | 7 CrewAI tool wrappers bridging to project tools |
| `civilmind/agents/crew.py` | `CivilMindCrew` — agent assembly and execution |
| `civilmind/agents/__init__.py` | Public API exports |

### Phase 7 — Vision

| File | Key exports |
|------|-------------|
| `civilmind/vision/ocr.py` | `OCREngine`, `OCRResult` — PaddleOCR wrapper |
| `civilmind/vision/floorplan.py` | `FloorPlanAnalyzer`, `DrawingAnalysis` — vision LLM for floor plans |
| `civilmind/vision/tables.py` | `TableExtractor`, `ExtractedTable`, `TableType` — table extraction from PDFs/images |
| `civilmind/vision/__init__.py` | Public API exports |

### Phase 8 — Knowledge Graph

| File | Key exports |
|------|-------------|
| `civilmind/graph/__init__.py` | Public API exports for all graph modules |
| `civilmind/graph/schema.py` | `NODE_LABELS`, `RELATIONSHIP_TYPES`, `VALID_EDGES`, `GraphEntity`, `GraphRelationship`, `CONSTRAINT_QUERIES` |
| `civilmind/graph/entities.py` | `EntityExtractor`, `ExtractedEntity`, `ExtractionResult` |
| `civilmind/graph/neo4j_store.py` | `Neo4jStore` — create, traverse, query, delete, health_check |
| `civilmind/graph/traversal.py` | `GraphTraversal`, `TraversalResult`, `GraphPath` — multi-hop queries |
| `civilmind/graph/graphrag.py` | `GraphRAG`, `GraphContext` — vector + graph → LLM answer |

### Phase 9 — Evaluation

| File | Key exports |
|------|-------------|
| `civilmind/evaluation/__init__.py` | Public API exports for all evaluation modules |
| `civilmind/evaluation/metrics.py` | `RetrievalMetrics`, `RetrievalMetricResult` — Recall@K, Precision@K, MRR, NDCG |
| `civilmind/evaluation/faithfulness.py` | `FaithfulnessChecker`, `FaithfulnessResult` — LLM-as-judge |
| `civilmind/evaluation/cost_tracker.py` | `CostTracker`, `QueryCost` — token usage and cost tracking |
| `civilmind/evaluation/benchmarks.py` | `BenchmarkRunner`, `BenchmarkCase`, `BenchmarkReport` — automated evaluation |

---

## Config -> File cross-reference

```
.env var                    → civilmind/settings.py:Field           → Used by
─────────────────────────────────────────────────────────────────────────────────
APP_NAME                    → APP_NAME                              → api/app.py
DEBUG                       → DEBUG                                 → (app-wide)
SECRET_KEY                  → SECRET_KEY                            → (future use)
POSTGRES_*                  → DATABASE_URL (property)               → db/models.py
QDRANT_HOST/PORT            → QDRANT_URL (property)                 → vector/qdrant_store.py
MINIO_*                     → MINIO_ENDPOINT, etc.                  → storage/minio_client.py
NEO4J_URI/USER/PASSWORD     → NEO4J_URI, etc.                      → graph/neo4j_store.py
REDIS_URL                   → REDIS_URL                             → events/bus.py
LLM_PROVIDER/API_KEY/BASE_URL/MODEL → llm_chat/vision_config       → llm/client.py
EMBEDDING_PROVIDER/MODEL    → EMBEDDING_PROVIDER, EMBEDDING_MODEL   → pipeline/embedder.py
SUPPORTED_DOC_FORMATS       → SUPPORTED_FORMATS (property)          → api/routes/upload.py
EMBEDDING_DIMS_CSV          → EMBEDDING_DIMS (property)             → config.py
OCR_MAX_IMAGE_SIZE_MB       → OCR_MAX_IMAGE_SIZE_MB                 → tools/ocr.py
VISION_MAX_IMAGE_SIZE_MB    → VISION_MAX_IMAGE_SIZE_MB              → tools/vision_llm.py
SQL_QUERY_TIMEOUT_SECONDS   → SQL_QUERY_TIMEOUT_SECONDS             → tools/sql_query.py
PADDLEOCR_ENABLED           → PADDLEOCR_ENABLED                     → pipeline/parser.py
TESSERACT_LANG              → TESSERACT_LANG                        → (future use)
```
