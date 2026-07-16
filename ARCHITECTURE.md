# Architecture — AI Knowledge Platform

> Domain-agnostic AI platform for document intelligence, multi-agent reasoning, and knowledge graph-powered question answering.
> Civil engineering is one plugin. The core engine is reusable across legal, medical, finance, and manufacturing.

---

## 0.1 Problem Statement

Enterprise teams accumulate massive document corpora (PDFs, drawings, spreadsheets, scanned images). Answering questions against these corpora requires:

1. **Document understanding** — parsing, OCR, table extraction, vision analysis
2. **Semantic retrieval** — finding relevant chunks across millions of pages
3. **Multi-hop reasoning** — connecting information across documents via knowledge graphs
4. **Domain expertise** — specialized agents for compliance, estimation, scheduling
5. **Auditability** — every answer must cite its sources and reasoning chain

Basic RAG (retrieve → generate) fails because:
- It retrieves but doesn't reason across documents
- It can't verify its own answers
- It doesn't understand visual content (floor plans, diagrams)
- It can't enforce domain rules (building codes, regulations)
- It has no memory of past interactions

---

## 0.2 System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                                │
│  Web App  │  CLI  │  API Consumer  │  Plugin (Civil/Legal/Medical)  │
└────────────────────────────┬────────────────────────────────────────┘
                             │ HTTP / SSE
┌────────────────────────────▼────────────────────────────────────────┐
│                          API GATEWAY                                 │
│  FastAPI  │  Rate Limiting  │  Auth  │  Request Validation          │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                      ORCHESTRATION LAYER                             │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    LangGraph Engine                          │   │
│  │                                                              │   │
│  │  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌────────┐  │   │
│  │  │ Planner  │──▶│ Retriever│──▶│ Analyst  │──▶│Reviewer│  │   │
│  │  └──────────┘   └──────────┘   └──────────┘   └────────┘  │   │
│  │       │              │              │              │         │   │
│  │       ▼              ▼              ▼              ▼         │   │
│  │  ┌─────────────────────────────────────────────────────┐   │   │
│  │  │              Tool Layer (Strategy Pattern)           │   │   │
│  │  │  VectorSearch │ SQLQuery │ OCR │ VisionLLM │ Calc   │   │   │
│  │  └─────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              CrewAI Worker Agents (Optional)                 │   │
│  │  Planner Agent │ Estimator Agent │ Compliance Agent │ ...    │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                      STORAGE LAYER                                   │
│                                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐  │
│  │PostgreSQL│ │  Qdrant  │ │  MinIO   │ │  Neo4j   │ │ Redis  │  │
│  │ (metadata│ │ (vectors)│ │ (files)  │ │  (graph) │ │(cache) │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                    EVENT-DRIVEN PIPELINE                             │
│                                                                     │
│  Upload ──▶ Redis Queue ──▶ Parser ──▶ Chunker ──▶ Embedder ──▶   │
│            ──▶ Graph Builder ──▶ Indexer ──▶ Ready                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                     OBSERVABILITY LAYER                              │
│                                                                     │
│  Structured Logs (structlog) │ Metrics (prometheus) │ Traces (OTEL) │
│  Evaluation (faithfulness, recall, hallucination) │ Cost Tracking    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 0.3 Request Lifecycle

### Query Request (Synchronous)

```
Client POST /api/query
  │
  ▼
API Gateway
  │ validate request
  │ rate limit check
  │ auth check
  │
  ▼
LangGraph Engine
  │
  ├──▶ Planner Node
  │     │ LLM call: analyze question, decide which nodes to run
  │     │ returns: next_nodes = ["retriever", "estimator"]
  │     │
  │     ├──▶ Retriever Node
  │     │     │ Tool call: VectorSearchTool.search(query, project_id)
  │     │     │   ──▶ BM25 search (top 20)
  │     │     │   ──▶ Vector search (top 20)
  │     │     │   ──▶ RRF merge (top 30)
  │     │     │   ──▶ Cross-encoder rerank (top 10)
  │     │     │   ──▶ Context compression (top 5)
  │     │     │ returns: retrieved_chunks
  │     │     │
  │     ├──▶ Compliance Node
  │     │     │ Tool call: CodeSearchTool.search(question)
  │     │     │ LLM call: check against building codes
  │     │     │ returns: violations
  │     │     │
  │     └──▶ Estimator Node
  │           │ Tool call: SQLQueryTool.query(material_db)
  │           │ LLM call: calculate quantities and costs
  │           │ returns: cost_estimation
  │
  ▼
Reviewer Node
  │ validate all outputs
  │ check confidence scores
  │ verify citation quality
  │
  ├──▶ if issues && iteration < 3: loop back to Planner
  └──▶ if valid: proceed to Reporter
  │
  ▼
Reporter Node
  │ LLM call: generate final answer with citations
  │
  ▼
Response
  │ {
  │   "answer": "...",
  │   "sources": [...],
  │   "reasoning_chain": [...],
  │   "confidence": 0.85,
  │   "cost": 0.02
  │ }
```

### Ingestion Request (Asynchronous)

```
Client POST /api/upload
  │
  ▼
API Gateway
  │ validate file type and size
  │ generate document_id
  │
  ▼
Redis Queue ("ingestion")
  │
  ▼
Parser Worker
  │ Unstructured: PDF → elements (text, table, image)
  │ PaddleOCR: scanned pages → text
  │ Vision LLM: floor plans → structural analysis
  │
  ▼
Chunker Worker
  │ Semantic splitting (threshold=0.5)
  │ Table → single chunk
  │ Image → caption chunk
  │ Metadata extraction (measurements, codes)
  │
  ▼
Embedder Worker
  │ BGE-base: text → 768-dim vector
  │ Cache by content hash
  │
  ▼
Graph Builder Worker
  │ Entity extraction (NER)
  │ Relationship mapping
  │ Neo4j insertion
  │
  ▼
Indexer Worker
  │ Qdrant upsert (vector + metadata)
  │ BM25 index rebuild
  │ PostgreSQL status update (ocr_status → done)
  │
  ▼
Document Ready
```

---

## 0.4 Domain Model

```
┌──────────────────────────────────────────────────────────────────┐
│                      CORE ENTITIES                                │
│                                                                   │
│  Project ──1:N──▶ Document ──1:N──▶ Chunk ──1:1──▶ Vector       │
│     │                                                         │  │
│     └──1:N──▶ Entity ──1:1──▶ GraphNode                    │  │
│                                                                   │
│  Query ──1:N──▶ RetrievalResult ──1:N──▶ Citation               │
│     │                                                         │  │
│     └──1:1──▶ WorkflowExecution ──1:N──▶ NodeExecution          │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### Entity Relationships

```
Project (top-level container)
  ├── Document (uploaded file)
  │     ├── Chunk (embeddable text piece)
  │     │     └── Vector (Qdrant point)
  │     ├── OCRResult (extracted text)
  │     └── VisionAnalysis (structural elements)
  ├── Entity (knowledge graph node)
  │     └── GraphNode (Neo4j node)
  ├── Query (user question)
  │     ├── RetrievalResult (search hit)
  │     │     └── Citation (source reference)
  │     └── WorkflowExecution (LangGraph run)
  │           └── NodeExecution (per-node log)
  └── Report (generated answer)
```

---

## 0.5 Data Flow

### Ingestion Flow

```
                    ┌─────────────┐
                    │   Upload    │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Validator  │
                    │ type, size  │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   Parser    │──── Unstructured / PaddleOCR
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Chunker    │──── Semantic splitting
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Embedder   │──── BGE-base / OpenCode Zen
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼──────┐ ┌──▼───┐ ┌─────▼─────┐
       │   Qdrant    │ │Redis │ │ PostgreSQL│
       │  (vectors)  │ │(cache)│ │  (meta)  │
       └─────────────┘ └──────┘ └───────────┘
```

### Query Flow

```
                    ┌─────────────┐
                    │   Query     │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Embedder   │──── query → vector
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼──────┐ ┌──▼──────┐ ┌──▼──────┐
       │    BM25     │ │ Vector  │ │ GraphRAG│
       │  (keyword)  │ │ (semantic)│ │ (multi-hop)│
       └──────┬──────┘ └──┬──────┘ └──┬──────┘
              │            │            │
              └────────────┼────────────┘
                           │
                    ┌──────▼──────┐
                    │    RRF      │──── Reciprocal Rank Fusion
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Reranker   │──── Cross-encoder
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Compressor │──── Extractive compression
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   LLM       │──── OpenCode Zen
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Response   │──── answer + citations
                    └─────────────┘
```

---

## 0.6 Agent Interaction

### LangGraph as Orchestrator (Primary)

```
                     ┌──────────────────┐
                     │    LangGraph     │
                     │   (StateGraph)   │
                     └────────┬─────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
       ┌──────▼──────┐ ┌─────▼─────┐ ┌──────▼──────┐
       │   Planner   │ │ Retriever │ │  Reviewer   │
       │   (LLM)     │ │  (Tools)  │ │  (LLM)     │
       └──────┬──────┘ └─────┬─────┘ └──────┬──────┘
              │               │               │
              └───────────────┼───────────────┘
                              │
                     ┌────────▼─────────┐
                     │    Tool Layer     │
                     │  (Strategy Pattern)│
                     └────────┬─────────┘
                              │
              ┌───────┬───────┼───────┬───────┐
              │       │       │       │       │
           Vector  SQL    OCR    Vision   Calc
           Search  Query        LLM
```

### CrewAI for Specialized Workers (Optional)

```
LangGraph delegates to CrewAI when:
  - Multi-step reasoning needed
  - Domain-specific expertise required
  - Parallel agent collaboration beneficial

CrewAI crew:
  ├── Planner Agent (delegates tasks)
  ├── Estimator Agent (calculations)
  ├── Compliance Agent (rule checking)
  ├── Reviewer Agent (validation)
  └── Report Agent (generation)
```

---

## 0.7 Deployment Architecture

### Development (Docker Compose)

```
┌─────────────────────────────────────────────┐
│              Docker Compose                  │
│                                              │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  │
│  │   API   │  │ PostgreSQL│  │  Qdrant   │  │
│  │ :8000   │  │  :5432    │  │  :6333    │  │
│  └─────────┘  └──────────┘  └───────────┘  │
│                                              │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  │
│  │  MinIO  │  │  Neo4j   │  │   Redis   │  │
│  │ :9000   │  │  :7687   │  │  :6379    │  │
│  └─────────┘  └──────────┘  └───────────┘  │
│                                              │
│  ┌─────────────────────────────────────────┐│
│  │           OCR Worker (separate)          ││
│  │  PaddleOCR + Tesseract + LibreOffice    ││
│  └─────────────────────────────────────────┘│
└─────────────────────────────────────────────┘
```

### Production (Kubernetes)

```
┌──────────────────────────────────────────────────────────────┐
│                     Kubernetes Cluster                         │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                    Ingress Controller                     │ │
│  └────────────────────────────┬────────────────────────────┘ │
│                               │                               │
│  ┌────────────────────────────▼────────────────────────────┐ │
│  │                    API Deployment                        │ │
│  │  Replicas: 3  │  CPU: 2  │  Memory: 4Gi                │ │
│  └────────────────────────────┬────────────────────────────┘ │
│                               │                               │
│  ┌────────────────────────────▼────────────────────────────┐ │
│  │                  Worker Deployment                       │ │
│  │  Replicas: 2-10 (HPA)  │  CPU: 4  │  Memory: 8Gi       │ │
│  └────────────────────────────┬────────────────────────────┘ │
│                               │                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │CloudSQL  │ │Memorystore│ │  GCS     │ │ Neo4j    │       │
│  │PostgreSQL│ │  Redis   │ │  (MinIO) │ │  Aura    │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

---

## 0.8 Module Structure

```
civilmind/
├── api/                    # HTTP layer (FastAPI)
│   ├── app.py              # App factory, middleware
│   ├── routes/             # Endpoint definitions
│   │   ├── health.py
│   │   ├── upload.py
│   │   ├── projects.py
│   │   ├── query.py
│   │   └── reports.py
│   └── dependencies.py     # DI container
│
├── domain/                 # Business logic (pure Python)
│   ├── models.py           # Domain entities
│   ├── exceptions.py       # Custom exceptions
│   └── events.py           # Domain events
│
├── infrastructure/         # External integrations
│   ├── database/
│   │   ├── engine.py       # SQLAlchemy async engine
│   │   ├── models.py       # ORM models
│   │   ├── session.py      # Session dependency
│   │   └── repositories.py # Repository pattern
│   ├── storage/
│   │   └── minio_client.py # MinIO wrapper
│   └── cache/
│       └── redis_client.py # Redis wrapper
│
├── workflow/               # LangGraph orchestration
│   ├── state.py            # TypedDict state model
│   ├── nodes.py            # Node implementations
│   ├── graph.py            # Graph builder + routing
│   └── checkpoint.py       # State persistence
│
├── agents/                 # CrewAI worker agents
│   ├── roles.py            # Agent definitions
│   ├── crew.py             # Crew assembly
│   └── prompts.py          # System prompts
│
├── tools/                  # Tool layer (Strategy pattern)
│   ├── base.py             # BaseTool ABC
│   ├── vector_search.py    # Qdrant search
│   ├── sql_query.py        # PostgreSQL queries
│   ├── code_search.py      # Building code lookup
│   ├── ocr.py              # PaddleOCR wrapper
│   ├── vision_llm.py       # OpenCode Zen vision
│   ├── calculator.py       # Math evaluation
│   └── registry.py         # Tool registry + DI
│
├── retrieval/              # RAG pipeline
│   ├── bm25_index.py       # BM25 keyword search
│   ├── vector_search.py    # Vector similarity
│   ├── reranker.py         # Cross-encoder reranking
│   ├── compressor.py       # Context compression
│   ├── hybrid.py           # Orchestrator
│   └── graphrag.py         # Graph-enhanced retrieval
│
├── vision/                 # Document understanding
│   ├── ocr.py              # PaddleOCR engine
│   ├── floorplan.py        # Floor plan analyzer
│   └── tables.py           # Table extractor
│
├── knowledge_graph/        # Neo4j graph operations
│   ├── schema.py           # Node/relationship definitions
│   ├── entities.py         # Entity extraction
│   ├── store.py            # Neo4j CRUD
│   └── traversal.py        # Multi-hop queries
│
├── pipeline/               # Ingestion pipeline
│   ├── parser.py           # Document parsing
│   ├── chunker.py          # Semantic chunking
│   ├── embedder.py         # Embedding service
│   └── orchestrator.py     # Pipeline coordination
│
├── events/                 # Event-driven processing
│   ├── bus.py              # Event bus (Redis Streams)
│   ├── handlers.py         # Event handlers
│   └── workers.py          # Background workers
│
├── evaluation/             # Quality framework
│   ├── metrics.py          # Retrieval + generation metrics
│   ├── faithfulness.py     # Hallucination detection
│   ├── cost_tracker.py     # Token cost tracking
│   └── benchmarks.py       # Evaluation datasets
│
├── config.py               # Design decisions
├── settings.py             # Deployment facts
└── __init__.py
```

---

## 0.9 Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Orchestration | LangGraph | Stateful graphs, checkpointing, conditional routing, human-in-the-loop |
| Worker Agents | CrewAI | Role-based, delegation, memory. Used only when multi-agent collaboration needed |
| Vector DB | Qdrant | Self-hosted, fast filtering, cosine similarity, easy local setup |
| Graph DB | Neo4j | Best for multi-hop traversal, Cypher query language |
| Embeddings | BGE-base (local) | Free, fast, good quality. OpenCode Zen for production |
| Event Queue | Redis Streams | Already in stack, supports consumer groups, backpressure |
| LLM Gateway | OpenCode Zen | Single key, OpenAI-compatible, curated model selection |
| Object Storage | MinIO | S3-compatible, self-hosted, easy migration to cloud |
| OCR | PaddleOCR | Free, accurate, multilingual. Separate worker for isolation |
| Framework | FastAPI | Async, auto-docs, Pydantic validation |

---

## 0.10 Interview Questions

### Architecture

1. **"Why LangGraph over simple if/else routing?"**
   LangGraph provides state persistence, checkpointing, conditional branching, and human-in-the-loop. Without it, you'd rebuild these features manually. It also enables time-travel debugging (replay any state).

2. **"Why separate the tool layer from agents?"**
   Agents become reusable and testable. A "Retriever" agent can use VectorSearchTool in production and a mock tool in tests. Tools can be shared across agents. Adding a new tool doesn't require changing agent code.

3. **"Why event-driven ingestion instead of synchronous?"**
   Large files (100+ pages) take minutes to parse + embed. Synchronous processing blocks the API. Event-driven: API returns immediately, workers process in background, user polls or gets webhook notification.

4. **"How do you handle hallucination?"**
   Three layers: (a) faithfulness scoring (LLM-as-judge checks if answer is supported by retrieved context), (b) citation enforcement (every claim must reference a source chunk), (c) reviewer node (validates outputs before final answer).

5. **"Why domain-agnostic instead of civil-engineering-specific?"**
   The core engine (retrieval, reasoning, graph traversal, evaluation) is reusable. Only the domain-specific agents, prompts, and schemas change. This is how production platforms are built — one engine, multiple verticals.

### Performance

6. **"What's the latency budget for a query?"**
   Target: <5s for simple queries, <15s for complex multi-agent. Breakdown: retrieval 200ms, reranking 100ms, LLM 2-10s (depends on model), graph traversal 50ms.

7. **"How do you scale OCR independently?"**
   Separate worker with Redis queue. Under load: add more worker pods (HPA on queue depth). API stays fast. OCR is the bottleneck, not the API.

8. **"What happens when BM25 returns 3 results but you need top-20?"**
   Below corpus-size threshold (<50 docs), skip BM25 entirely and use pure vector search. Above threshold: pad with lower-ranked results, weight RRF dynamically based on candidate count.
