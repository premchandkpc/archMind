# Implementation Plan — AI Knowledge Platform

> Domain-agnostic AI platform. Build incrementally. Every phase compiles and runs before the next.
> See [ARCHITECTURE.md](ARCHITECTURE.md) for system design, data flow, and deployment architecture.

---

## Phase 0: Architecture (Done)

**Status:** Complete

- [x] ARCHITECTURE.md — system design, request lifecycle, domain model, data flow
- [x] Config vs Settings boundary
- [x] Fail-fast secrets
- [x] Embedding dim as derived lookup
- [x] Docker API/OCR worker split

---

## Phase 1: Foundation

> Build the skeleton: config, API, database, vector store, file storage, event bus.
> Every subsequent phase plugs into these foundations.

### 1.1 — Project Skeleton ✅

**Status:** Done

Files: `pyproject.toml`, `config.py`, `settings.py`, `Dockerfile`, `.env.example`

### 1.2 — FastAPI App ✅

**Status:** Done

Files: `api/app.py`, `api/routes/health.py`, `api/routes/upload.py`

### 1.3 — PostgreSQL Models + Migrations ✅

**Status:** Done

Files: `infrastructure/database/engine.py`, `models.py`, `session.py`, Alembic setup

### 1.4 — Qdrant Vector Store ✅

**Status:** Done

Files: `vector/qdrant_store.py`

### 1.5 — MinIO Object Storage ✅

**Status:** Done

Files: `storage/minio_client.py`

### 1.6 — Redis Event Bus ✅

**Status:** Done

Files: `events/bus.py`

---

## Phase 2: Tool Layer

> Agents should never query databases directly.
> Tools are the interface between agents and infrastructure.
> Strategy pattern: swap implementations without changing agent code.

### 2.1 — Tool Registry + Base

**Status:** Pending

**Goal:** Abstract tool interface with DI container.

**Files:**
| File | Purpose |
|------|---------|
| `tools/base.py` | BaseTool ABC, ToolResult dataclass |
| `tools/registry.py` | ToolRegistry: register, get, list |
| `tools/dependencies.py` | FastAPI DI for tool injection |

**Design:**
```python
class BaseTool(ABC):
    name: str
    description: str
    
    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult: ...

class ToolResult:
    success: bool
    data: Any
    error: str | None
    latency_ms: float
    tokens_used: int | None
```

### 2.2 — VectorSearch Tool

**Status:** Pending

**Goal:** Semantic + keyword search via hybrid retriever.

**Files:**
| File | Purpose |
|------|---------|
| `tools/vector_search.py` | VectorSearchTool: search, search_batch |

### 2.3 — SQLQuery Tool

**Status:** Pending

**Goal:** Read-only SQL queries against PostgreSQL.

**Files:**
| File | Purpose |
|------|---------|
| `tools/sql_query.py` | SQLQueryTool: execute (read-only, parameterized) |

**Security:** Read-only connection, no DDL, parameterized queries only, query timeout 5s.

### 2.4 — OCR + Vision Tools

**Status:** Pending

**Goal:** PaddleOCR and vision LLM tools.

**Files:**
| File | Purpose |
|------|---------|
| `tools/ocr.py` | OCRTool: extract_text, extract_all |
| `tools/vision_llm.py` | VisionLLMTool: analyze_image |

### 2.5 — Calculator + CodeSearch Tools

**Status:** Pending

**Goal:** Math evaluation and building code lookup.

**Files:**
| File | Purpose |
|------|---------|
| `tools/calculator.py` | CalculatorTool: safe math eval |
| `tools/code_search.py` | CodeSearchTool: search regulations |

---

## Phase 3: Ingestion Pipeline

> Event-driven document processing.
> Upload → Queue → Parse → Chunk → Embed → Graph → Index → Ready.
> Each step is independent, retryable, and horizontally scalable.

### 3.1 — Document Parser

**Status:** Pending

**Goal:** Parse PDF, DOCX, Excel, images into structured elements.

**Files:**
| File | Purpose |
|------|---------|
| `pipeline/parser.py` | DocumentParser: parse, classify elements |

**Element types:** Text, Table, Image, Title, ListItem
**OCR fallback:** Scanned PDFs → PaddleOCR → text elements

### 3.2 — Chunker + Metadata

**Status:** Pending

**Goal:** Semantic chunking with rich metadata extraction.

**Files:**
| File | Purpose |
|------|---------|
| `pipeline/chunker.py` | SemanticChunker: split by meaning, not fixed size |
| `pipeline/metadata.py` | MetadataExtractor: measurements, code refs, keywords |

**Strategy:**
- Text → SemanticSplitter (threshold=0.5)
- Table → single chunk (don't break tables)
- Image → caption chunk + image_path reference

### 3.3 — Embedding Service

**Status:** Pending

**Goal:** Convert text to vectors. BGE-local for dev, OpenCode Zen for prod.

**Files:**
| File | Purpose |
|------|---------|
| `pipeline/embedder.py` | BGEEmbedder, OpenCodeEmbedder, CachedEmbedder |

**Caching:** SHA256 hash → .cache/embeddings/ → skip recompute

### 3.4 — Pipeline Orchestrator

**Status:** Pending

**Goal:** Coordinate the full ingestion pipeline via Redis events.

**Files:**
| File | Purpose |
|------|---------|
| `pipeline/orchestrator.py` | IngestionPipeline: publish, consume, coordinate |
| `events/handlers.py` | Event handlers for each pipeline stage |

**Flow:**
```
Upload → publish("document.uploaded")
  → Parser subscribes → publish("document.parsed")
  → Chunker subscribes → publish("document.chunked")
  → Embedder subscribes → publish("document.embedded")
  → Indexer subscribes → publish("document.indexed")
  → Ready
```

**Retry:** Exponential backoff, max 3 attempts, dead-letter queue on failure.

---

## Phase 4: Retrieval

> Hybrid RAG with reranking and context compression.
> BM25 + Vector + GraphRAG → RRF → Rerank → Compress → LLM.

### 4.1 — BM25 Index

**Status:** Pending

**Goal:** Keyword search for exact term matching.

**Files:**
| File | Purpose |
|------|---------|
| `retrieval/bm25_index.py` | BM25Index: build, search, add, remove |

### 4.2 — Hybrid Retriever

**Status:** Pending

**Goal:** Combine BM25 + Vector with RRF fusion.

**Files:**
| File | Purpose |
|------|---------|
| `retrieval/hybrid.py` | HybridRetriever: full pipeline orchestrator |
| `retrieval/reranker.py` | CrossEncoderReranker: ms-marco-MiniLM |
| `retrieval/compressor.py` | ContextCompressor: extractive compression |

**Fallback:** Below MIN_CORPUS_FOR_BM25 (50 docs), skip BM25, pure vector.

### 4.3 — GraphRAG

**Status:** Pending

**Goal:** Vector search + graph traversal for multi-hop reasoning.

**Files:**
| File | Purpose |
|------|---------|
| `retrieval/graphrag.py` | GraphRAG: retrieve, answer with graph context |

---

## Phase 5: LangGraph Orchestration

> LangGraph is the backbone. Every request flows through it.
> State persists via PostgreSQL checkpointer.
> Conditional routing, retries, human-in-the-loop.

### 5.1 — State Model

**Status:** Pending

**Goal:** TypedDict flowing through the graph. Annotated reducers for accumulation.

**Files:**
| File | Purpose |
|------|---------|
| `workflow/state.py` | ProjectState, helper types, state factory |

### 5.2 — Graph Nodes

**Status:** Pending

**Goal:** Async functions that read/write state. Each node is independently testable.

**Files:**
| File | Purpose |
|------|---------|
| `workflow/nodes.py` | 10 nodes: planner, retriever, analyst, reviewer, reporter, etc. |

**Key principle:** Nodes call tools, not databases directly.

### 5.3 — Graph Builder + Routing

**Status:** Pending

**Goal:** Assemble StateGraph with conditional edges.

**Files:**
| File | Purpose |
|------|---------|
| `workflow/graph.py` | build_graph, route_after_planner, route_after_review |
| `workflow/checkpoint.py` | PostgresSaver for state persistence |

**Loop:** Reviewer → Planner (max 3 iterations) → Reporter → END

---

## Phase 6: Agents + CrewAI

> CrewAI agents collaborate when multi-step reasoning is needed.
> LangGraph delegates to CrewAI for complex domain tasks.
> Agents use tools from Phase 2, never query databases directly.

### 6.1 — Agent Definitions

**Status:** Pending

**Goal:** 9 specialized agents with roles, goals, tools.

**Files:**
| File | Purpose |
|------|---------|
| `agents/roles.py` | AgentFactory: create agents with role/goal/backstory |
| `agents/prompts.py` | System prompts per agent |

### 6.2 — Crew Orchestration

**Status:** Pending

**Goal:** Assemble CrewAI crew, hierarchical delegation.

**Files:**
| File | Purpose |
|------|---------|
| `agents/crew.py` | CivilMindCrew: create_agents, create_tasks, run |

---

## Phase 7: Vision + OCR

> Analyze floor plans, extract tables, OCR scanned documents.
> PaddleOCR for text extraction. Vision LLM for structural analysis.
> Runs as separate worker (Docker isolation).

### 7.1 — OCR Engine

**Status:** Pending

**Goal:** PaddleOCR for scanned document text extraction.

**Files:**
| File | Purpose |
|------|---------|
| `vision/ocr.py` | OCREngine: extract_text, extract_all |

### 7.2 — Floor Plan Analysis

**Status:** Pending

**Goal:** Vision LLM analyzes floor plans for structural elements.

**Files:**
| File | Purpose |
|------|---------|
| `vision/floorplan.py` | FloorPlanAnalyzer: analyze → DrawingAnalysis |

### 7.3 — Table Extraction

**Status:** Pending

**Goal:** Extract tables from PDFs and images. Classify as BOQ/spec/schedule.

**Files:**
| File | Purpose |
|------|---------|
| `vision/tables.py` | TableExtractor: extract_from_pdf, extract_from_image |

---

## Phase 8: Knowledge Graph

> Neo4j graph: Building → Floor → Room → Wall → Beam → Material → Vendor.
> Enables multi-hop reasoning: "What vendor supplies concrete for Bedroom 1?"

### 8.1 — Neo4j Schema + Ingestion

**Status:** Pending

**Goal:** Graph schema (12 node types, 12 relationship types). Entity extraction.

**Files:**
| File | Purpose |
|------|---------|
| `knowledge_graph/schema.py` | NODE_LABELS, RELATIONSHIPS |
| `knowledge_graph/entities.py` | EntityExtractor: NER from documents |
| `knowledge_graph/store.py` | Neo4jStore: CRUD, constraints |

### 8.2 — Graph Traversal + Multi-hop

**Status:** Pending

**Goal:** Combine vector search with graph traversal.

**Files:**
| File | Purpose |
|------|---------|
| `knowledge_graph/traversal.py` | GraphTraversal: find_paths, multi_hop |

---

## Phase 9: Evaluation

> An AI system without evaluation is untrustworthy.
> Measure retrieval quality, generation faithfulness, latency, cost.

### 9.1 — Retrieval Metrics

**Status:** Pending

**Goal:** Recall@K, Precision@K, MRR, NDCG.

**Files:**
| File | Purpose |
|------|---------|
| `evaluation/metrics.py` | RetrievalMetrics: recall, precision, mrr, ndcg |

### 9.2 — Generation Metrics

**Status:** Pending

**Goal:** Faithfulness, hallucination detection, answer relevance.

**Files:**
| File | Purpose |
|------|---------|
| `evaluation/faithfulness.py` | FaithfulnessChecker: LLM-as-judge |
| `evaluation/cost_tracker.py` | CostTracker: token counting, cost per query |

### 9.3 — Evaluation Pipeline

**Status:** Pending

**Goal:** Automated evaluation against benchmark datasets.

**Files:**
| File | Purpose |
|------|---------|
| `evaluation/benchmarks.py` | BenchmarkRunner: run eval, generate report |

---

## Phase 10: API Layer + Deployment

> Expose the system via HTTP. Deploy with Docker Compose / Kubernetes.

### 10.1 — Project CRUD

**Status:** Pending

**Goal:** Full CRUD for projects with cascade delete.

**Files:**
| File | Purpose |
|------|---------|
| `api/routes/projects.py` | 5 endpoints: POST, GET, GET/{id}, PATCH, DELETE |

### 10.2 — Query + Reports

**Status:** Pending

**Goal:** POST /api/query runs LangGraph workflow. SSE streaming for long queries.

**Files:**
| File | Purpose |
|------|---------|
| `api/routes/query.py` | POST /, POST /stream |
| `api/routes/reports.py` | GET /, GET/{id}, GET/{id}/download |

### 10.3 — Docker Compose

**Status:** Pending

**Goal:** 7 services: API, Worker, PostgreSQL, Qdrant, MinIO, Neo4j, Redis.

**Files:**
| File | Purpose |
|------|---------|
| `docker-compose.yml` | Full stack with health checks |

### 10.4 — Observability

**Status:** Pending

**Goal:** Structured logs, Prometheus metrics, OpenTelemetry traces.

**Files:**
| File | Purpose |
|------|---------|
| `infrastructure/observability/logging.py` | structlog configuration |
| `infrastructure/observability/metrics.py` | Prometheus counters, histograms |
| `infrastructure/observability/tracing.py` | OpenTelemetry setup |

---

## Execution Order

```
Phase 1:  1.1 ✓ → 1.2 ✓ → 1.3 ✓ → 1.4 → 1.5 → 1.6
Phase 2:  2.1 → 2.2 → 2.3 → 2.4 → 2.5
Phase 3:  3.1 → 3.2 → 3.3 → 3.4
Phase 4:  4.1 → 4.2 → 4.3
Phase 5:  5.1 → 5.2 → 5.3
Phase 6:  6.1 → 6.2
Phase 7:  7.1 → 7.2 → 7.3
Phase 8:  8.1 → 8.2
Phase 9:  9.1 → 9.2 → 9.3
Phase 10: 10.1 → 10.2 → 10.3 → 10.4

Status: 7/34 chunks complete. Phase 1 Foundation: Done. Phase 2 Tool Layer: 1/5. Next: 2.2 (VectorSearch Tool)
```

---

## Tech Stack

| Component | Technology | Why |
|-----------|------------|-----|
| API | FastAPI + uvicorn | Async, auto-docs, Pydantic validation |
| Database | PostgreSQL + SQLAlchemy | JSONB, full-text search, ACID |
| Vector DB | Qdrant | Self-hosted, fast filtering, cosine similarity |
| Object Storage | MinIO | S3-compatible, self-hosted |
| Graph DB | Neo4j | Multi-hop traversal, Cypher |
| Cache / Queue | Redis | Streams + cache in one |
| Embeddings | BGE-base (local) | Free, fast, good quality |
| LLM | OpenCode Zen | Single key, OpenAI-compatible |
| Orchestration | LangGraph | Stateful graphs, checkpointing |
| Worker Agents | CrewAI | Role-based, delegation |
| OCR | PaddleOCR | Free, accurate, multilingual |
| Parsing | Unstructured | All document types |
| Reranking | Cross-encoder | Precision ranking |
| Evaluation | LLM-as-judge | Faithfulness, hallucination |
| Observability | structlog + prometheus + OTEL | Logs, metrics, traces |
| Deployment | Docker Compose / K8s | Dev → prod |
