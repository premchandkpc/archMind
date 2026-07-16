# AI Knowledge Platform

Domain-agnostic AI platform for document intelligence, multi-agent reasoning, and knowledge graph-powered question answering. Civil engineering is one plugin. The core engine is reusable across legal, medical, finance, and manufacturing.

## What this is

Not a RAG chatbot. A production AI platform with:

- **LangGraph orchestration** — stateful workflows with checkpointing, conditional routing, human-in-the-loop
- **Tool layer** — agents never query databases directly; Strategy pattern makes tools swappable and testable
- **Event-driven ingestion** — async pipeline: Upload → Parse → Chunk → Embed → Graph → Index
- **Hybrid RAG** — BM25 + Vector + GraphRAG with RRF fusion and cross-encoder reranking
- **Knowledge graphs** — Neo4j for multi-hop reasoning: `Entity → Relationship → Entity`
- **Evaluation** — faithfulness scoring, hallucination detection, retrieval metrics, cost tracking
- **Observability** — structured logs, Prometheus metrics, OpenTelemetry traces

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for:
- System architecture diagram
- Request lifecycle (query + ingestion)
- Domain model
- Data flow
- Deployment architecture (Docker Compose → Kubernetes)
- Key design decisions

## Module structure

```
civilmind/
├── api/                    # FastAPI HTTP layer
├── domain/                 # Business logic (pure Python)
├── infrastructure/         # External integrations (DB, storage, cache, observability)
├── workflow/               # LangGraph orchestration
├── agents/                 # CrewAI worker agents
├── tools/                  # Tool layer (Strategy pattern)
├── retrieval/              # Hybrid RAG + GraphRAG
├── vision/                 # OCR + floor plan analysis
├── knowledge_graph/        # Neo4j graph operations
├── pipeline/               # Ingestion pipeline
├── events/                 # Event-driven processing (Redis Streams)
├── evaluation/             # Quality framework
├── config.py               # Design decisions
└── settings.py             # Deployment facts
```

## Setup

```bash
pip install -e ".[dev]"
cp .env.example .env  # fill in credentials
uvicorn civilmind.api.app:app --reload
```

**Required env vars** (app won't start without these):

| Variable | Purpose |
|----------|---------|
| `OPENCODE_API_KEY` | OpenCode Zen API key |
| `LLM_MODEL` | e.g. `opencode/claude-sonnet-4-5` |
| `VISION_MODEL` | e.g. `opencode/gpt-5` |
| `EMBEDDING_MODEL` | Must exist in `config.py EMBEDDING_DIMS` |

## Implementation status

| Phase | Chunks | Status |
|-------|--------|--------|
| 0. Architecture | ARCHITECTURE.md | Done |
| 1. Foundation | 1.1 ✓ 1.2 ✓ 1.3 ✓ 1.4 1.5 1.6 | 3/6 |
| 2. Tool Layer | 2.1 2.2 2.3 2.4 2.5 | 0/5 |
| 3. Ingestion | 3.1 3.2 3.3 3.4 | 0/4 |
| 4. Retrieval | 4.1 4.2 4.3 | 0/3 |
| 5. LangGraph | 5.1 5.2 5.3 | 0/3 |
| 6. Agents | 6.1 6.2 | 0/2 |
| 7. Vision | 7.1 7.2 7.3 | 0/3 |
| 8. Knowledge Graph | 8.1 8.2 | 0/2 |
| 9. Evaluation | 9.1 9.2 9.3 | 0/3 |
| 10. API + Deploy | 10.1 10.2 10.3 10.4 | 0/4 |

**Total: 3/34 chunks complete.**

See [PLAN.md](PLAN.md) for detailed specs. See [plan/](plan/) for per-chunk implementation plans.

## License

TBD
