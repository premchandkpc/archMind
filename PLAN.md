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

### 2.1 — Tool Registry + Base ✅

**Status:** Done

**Files:** `tools/base.py`, `tools/registry.py`

### 2.2 — VectorSearch Tool ✅

**Status:** Done

**Files:** `tools/vector_search.py`

### 2.3 — SQLQuery Tool ✅

**Status:** Done

**Files:** `tools/sql_query.py`

### 2.4 — OCR + Vision Tools ✅

**Status:** Done

**Files:** `tools/ocr.py`, `tools/vision_llm.py`

### 2.5 — Calculator + CodeSearch Tools ✅

**Status:** Done

**Files:** `tools/calculator.py`, `tools/code_search.py`

---

## Phase 3: Ingestion Pipeline

> Event-driven document processing.
> Upload → Queue → Parse → Chunk → Embed → Graph → Index → Ready.
> Each step is independent, retryable, and horizontally scalable.

### 3.1 — Document Parser ✅

**Status:** Done

**Files:** `pipeline/parser.py`

### 3.2 — Chunker + Metadata ✅

**Status:** Done

**Files:** `pipeline/chunker.py`, `pipeline/metadata.py`

### 3.3 — Embedding Service ✅

**Status:** Done

**Files:** `pipeline/embedder.py`

### 3.4 — Pipeline Orchestrator ✅

**Status:** Done

**Files:** `pipeline/orchestrator.py`, `events/handlers.py`, `pipeline/workers.py`

---

## Phase 4: Retrieval

> Hybrid RAG with reranking and context compression.
> BM25 + Vector + GraphRAG → RRF → Rerank → Compress → LLM.

### 4.1 — BM25 Index ✅

**Status:** Done

**Files:** `retrieval/bm25_index.py`

### 4.2 — Hybrid Retriever ✅

**Status:** Done

**Files:** `retrieval/hybrid.py`, `retrieval/reranker.py`, `retrieval/compressor.py`

### 4.3 — GraphRAG ✅

**Status:** Done

**Files:** `graph/graphrag.py`

---

## Phase 5: LangGraph Orchestration

> LangGraph is the backbone. Every request flows through it.
> State persists via PostgreSQL checkpointer.
> Conditional routing, retries, human-in-the-loop.

### 5.1 — State Model ✅

**Status:** Done

**Files:** `workflow/state.py`

### 5.2 — Graph Nodes ✅

**Status:** Done

**Files:** `workflow/nodes.py`

### 5.3 — Graph Builder + Routing ✅

**Status:** Done

**Files:** `workflow/graph.py`, `workflow/checkpoint.py`

---

## Phase 6: Agents + CrewAI

> CrewAI agents collaborate when multi-step reasoning is needed.
> LangGraph delegates to CrewAI for complex domain tasks.
> Agents use tools from Phase 2, never query databases directly.

### 6.1 — Agent Definitions ✅

**Status:** Done

**Files:** `agents/roles.py`, `agents/prompts.py`

### 6.2 — Crew Orchestration ✅

**Status:** Done

**Files:** `agents/crew.py`

---

## Phase 7: Vision + OCR

> Analyze floor plans, extract tables, OCR scanned documents.
> PaddleOCR for text extraction. Vision LLM for structural analysis.
> Runs as separate worker (Docker isolation).

### 7.1 — OCR Engine ✅

**Status:** Done

**Files:** `vision/ocr.py`

### 7.2 — Floor Plan Analysis ✅

**Status:** Done

**Files:** `vision/floorplan.py`

### 7.3 — Table Extraction ✅

**Status:** Done

**Files:** `vision/tables.py`

---

## Phase 8: Knowledge Graph

> Neo4j graph: Building → Floor → Room → Wall → Beam → Material → Vendor.
> Enables multi-hop reasoning: "What vendor supplies concrete for Bedroom 1?"

### 8.1 — Neo4j Schema + Ingestion ✅

**Status:** Done

**Files:** `graph/schema.py`, `graph/entities.py`, `graph/neo4j_store.py`

### 8.2 — Graph Traversal + Multi-hop ✅

**Status:** Done

**Files:** `graph/traversal.py`, `graph/graphrag.py`

---

## Phase 9: Evaluation

> An AI system without evaluation is untrustworthy.
> Measure retrieval quality, generation faithfulness, latency, cost.

### 9.1 — Retrieval Metrics ✅

**Status:** Done

**Files:** `evaluation/metrics.py`

### 9.2 — Generation Metrics ✅

**Status:** Done

**Files:** `evaluation/faithfulness.py`, `evaluation/cost_tracker.py`

### 9.3 — Evaluation Pipeline ✅

**Status:** Done

**Files:** `evaluation/benchmarks.py`

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
Phase 1:  1.1 ✓ → 1.2 ✓ → 1.3 ✓ → 1.4 ✓ → 1.5 ✓ → 1.6 ✓
Phase 2:  2.1 ✓ → 2.2 ✓ → 2.3 ✓ → 2.4 ✓ → 2.5 ✓
Phase 3:  3.1 ✓ → 3.2 ✓ → 3.3 ✓ → 3.4 ✓
Phase 4:  4.1 ✓ → 4.2 ✓ → 4.3 ✓
Phase 5:  5.1 ✓ → 5.2 ✓ → 5.3 ✓
Phase 6:  6.1 ✓ → 6.2 ✓
Phase 7:  7.1 ✓ → 7.2 ✓ → 7.3 ✓
Phase 8:  8.1 ✓ → 8.2 ✓
Phase 9:  9.1 ✓ → 9.2 ✓ → 9.3 ✓
Phase 10: 10.1 → 10.2 → 10.3 → 10.4

Status: 31/34 chunks complete. Phases 1–9 Done. Next: 10.1 (Project CRUD)
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
