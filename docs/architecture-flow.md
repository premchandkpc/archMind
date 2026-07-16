# Architecture Flows — Phases 1–5

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

Response: `202 Accepted` with `{"document_id": ..., "status": "processing"}`

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
        +-----------+-----------+
        |           |           |
    retriever  estimator  compliance
        |           |           |
        +-----------+-----------+
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
  → picks first node from list

route_after_review(state)  → [workflow/graph.py:61]
  if review_feedback.is_valid → "reporter"
  if iteration < MAX_ITERATIONS → "planner" (loop)
  else → "reporter" (force exit)
```

---

## File inventory (Phases 1-5)

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
NEO4J_URI/USER/PASSWORD     → NEO4J_URI, etc.                      → (future Phase 8)
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
