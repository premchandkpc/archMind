# AGENTS.md — CivilMind AI Project Rules

## Commands

**ALWAYS use the Makefile.** Never run raw `python`, `uvicorn`, `pytest`, `alembic`, or `docker` commands directly.

```bash
# Setup
make setup          # venv + deps + .env
make quickstart     # setup + docker-up + db-migrate

# Run
make run            # production server
make run-dev        # dev server with auto-reload

# Test
make test           # all tests
make test-unit      # unit tests only
make test-live      # live integration tests
make test-tools     # verify all tools load
make health         # check all service connectivity

# Lint / Format / Type
make lint           # ruff check
make format         # ruff format + fix
make typecheck      # mypy

# Database
make db-migrate     # apply migrations
make db-migrate-new MSG="description"  # create new migration
make db-down        # rollback one
make db-current     # show current version
make db-history     # show all versions

# Docker
make docker-up      # start all services
make docker-down    # stop all services
make docker-ps      # show running containers
make docker-logs    # tail all logs
make docker-restart # stop + start

# Individual Docker services
make docker-postgres
make docker-qdrant
make docker-minio
make docker-neo4j
make docker-redis

# Build
make build          # Python package
make build-docker   # Docker image
```

## Config Rules — ZERO Hardcoded Values

**Every configurable value must come from `.env`.** Never hardcode secrets, URLs, ports, hosts, or tunable parameters in `.py` files.

### Where things go

| Layer | File | What goes there | Example |
|-------|------|----------------|---------|
| **Env** | `.env` (gitignored) | Secrets, hosts, ports, URLs, model names | `LLM_API_KEY`, `POSTGRES_HOST`, `EMBEDDING_MODEL` |
| **Template** | `.env.example` (tracked) | All env vars with placeholder values | Copy to `.env` and fill |
| **Settings** | `civilmind/settings.py` | `Field(default=...)` for every env var | `POSTGRES_HOST: str = Field(default="localhost")` |
| **Config** | `civilmind/config.py` | Code-level design decisions (non-tunable) | Chunk size, top_k, algorithm choices |

### Rules

1. **Secrets → `.env` only.** Never in code, never committed.
2. **URLs → `.env` only.** `Field(default="...")` for sensible dev defaults, but user can always override.
3. **Ports/hosts → `.env` only.** No `localhost:5432` hardcoded outside `settings.py`.
4. **Tool parameters (timeouts, limits, max sizes) → `.env` → `settings.py`**.
5. **Code logic (safe ops, read-only keyword list, regulation data) → stays in Python files.** These are not config.

### How to add a new env var

1. Add `MY_VAR: str = Field(default="val")` to `Settings` in `settings.py`
2. Add `MY_VAR=val` to `.env.example`
3. Add `MY_VAR=val` to your local `.env`
4. Reference via `settings.MY_VAR` anywhere in the codebase

### Provider config pattern

```env
# Generic LLM (works with any OpenAI-compatible API)
LLM_PROVIDER=opencode  # opencode | openai | anthropic | custom
LLM_API_KEY=sk-...
LLM_BASE_URL=https://opencode.ai/zen/v1
LLM_CHAT_MODEL=opencode/claude-sonnet-4-5
LLM_VISION_MODEL=opencode/gpt-5

# Provider-specific (anthropic only)
ANTHROPIC_API_URL=https://api.anthropic.com/v1/messages
ANTHROPIC_VERSION=2023-06-01
```

## Coding Standards

### Python version & imports

- Python 3.11+, async throughout. Use `list[X]` not `List[X]`, `dict[K,V]` not `Dict[K,V]`, `str | None` not `Optional[str]`.
- Imports order: stdlib → third-party → local. One blank line between groups.
- Always use `from __future__ import annotations` at the top of every `.py` file.
- Use structlog everywhere: `import structlog` then `logger = structlog.get_logger()` at module level.

### Naming conventions

| Thing | Convention | Example |
|-------|-----------|---------|
| Files/dirs | snake_case | `vector_search.py`, `qdrant_store.py` |
| Classes | PascalCase | `VectorSearchTool`, `QdrantStore` |
| Functions | snake_case | `get_embedding_dim()`, `_build_filter()` |
| Variables | snake_case | `query_vector`, `project_id` |
| Constants | UPPER_CASE | `MAX_IMAGE_SIZE_MB`, `READ_ONLY_KEYWORDS` |
| Private methods | `_` prefix | `_get_engine()`, `_build_filter()` |
| Settings properties | UPPER_CASE (preserve env var name) | `DATABASE_URL`, `QDRANT_URL` |

### Type annotations

- Every function/method must have type annotations on all parameters and return types.
- Use `str | None` not `Optional[str]`.
- Use `list[dict[str, str]]` not `List[Dict[str, str]]`.
- Use `Any` only as last resort — prefer specific types.

```python
async def execute(self, query: str, project_id: str, top_k: int = 10) -> ToolResult: ...
```

### Async patterns

- All I/O must be async. No blocking calls in request handlers.
- Use `async def` / `await` everywhere. No `asyncio.run()` inside async code.
- For sync libraries (e.g. PaddleOCR, Qdrant client), wrap the sync call as-is but call it from an async function. The sync library is called in a separate thread pool if it blocks.
- Connection cleanup: use `try/finally` or `async with` context managers.

```python
conn: asyncpg.Connection | None = None
try:
    conn = await asyncpg.connect(dsn)
    ...
finally:
    if conn:
        await conn.close()
```

### Error handling

- Tools: never let exceptions escape `execute()`. Catch everything, return `ToolResult(success=False, error=str(...))`.
- API endpoints: raise `HTTPException` for expected errors.
- Internal code: let exceptions propagate up to the tool/API boundary.
- Always log errors with `logger.error("...", error=str(e))`.

```python
try:
    result = await self._client.query(...)
except Exception as e:
    logger.error("Search failed", error=str(e))
    return ToolResult(success=False, error=f"{type(e).__name__}: {e}")
```

### Docstrings

- Module docstring: `"""Short description."""` at the top of every `.py` file.
- Class docstring: `"""Description of what this class does."""`
- Method docstring: Google style with Args/Returns sections for public methods.

```python
def execute(self, query: str, project_id: str) -> ToolResult:
    """Short summary.

    Args:
        query: Description.
        project_id: Description.

    Returns:
        ToolResult with the data.
    """
```

### Dataclass patterns

- Use `@dataclass` for data containers (results, configs). Use `field(default_factory=...)` for mutable defaults.
- Use `@dataclass(frozen=True)` for immutable config objects.

```python
@dataclass
class ToolResult:
    success: bool
    data: Any = None
    error: str | None = None
    metadata: dict = field(default_factory=dict)
```

### Tool contract (Phase 2+)

- Every tool extends `BaseTool`, implements `execute()`, returns `ToolResult`.
- Tools never access databases directly — they go through store wrappers (QdrantStore, MinIOStorage, etc.).
- All tools are registered in `ToolRegistry` at startup.

```python
class MyTool(BaseTool):
    name = "my_tool"
    description = "What it does"
    category = "retrieval"  # retrieval | data | vision | calculation | knowledge

    async def execute(self, **kwargs: Any) -> ToolResult: ...
```

### File structure

```
civilmind/
├── api/           # FastAPI routes, middleware
├── db/            # SQLAlchemy models, engine, session
├── events/        # Redis event bus
├── llm/           # LLM client (provider-agnostic)
├── pipeline/      # Document ingestion pipeline
├── retrieval/     # BM25, hybrid retriever, reranker
├── storage/       # MinIO object storage
├── tools/         # All agent-callable tools
├── vector/        # Qdrant vector store wrapper
├── workflow/      # State machine, graph builder
├── agents/        # Agent definitions
├── graph/         # Neo4j knowledge graph
├── vision/        # OCR, vision analysis
├── config.py      # Code-level design constants
└── settings.py    # Env var definitions
```

### Lint / format / type

Always run before committing:

```bash
make format    # ruff format + fix
make lint      # ruff check
make typecheck # mypy (strict mode)
```

Mypy runs in strict mode with `pydantic.mypy` plugin. Ruff enforces: E, F, I, N, UP rules. Line length: 100.

## Project Conventions

- Python 3.11+, async throughout (FastAPI, SQLAlchemy async, redis.asyncio)
- Self-hosted infrastructure — no cloud dependencies
- Phase-by-phase incremental delivery
- Tools are swappable — agents never access DBs directly
- All tools return `ToolResult(success, data, error, latency_ms)`
- Tests must pass against live Docker services
- `Makefile` drives everything — never run raw commands
- X-Request-ID middleware on every request for traceability

## Files

- `Makefile` — all commands
- `pyproject.toml` — dependencies and tool config
- `Dockerfile` — app image
- `.env` — local config (gitignored)
- `.env.example` — config template (tracked)
- `civilmind/settings.py` — all env var definitions
- `civilmind/config.py` — code-level design constants
- `civilmind/` — all application code
- `scripts/` — standalone scripts (health checks, DB reset, tool tests)
- `plan/` — phase completion tracking

## Doc Rules — Plan Hygiene

### Renumbering a plan file

Whenever a `plan/N.M-*.md` file is renumbered or split:

1. **Rename the file** to `plan/NEW.NEW-*.md`.
2. **Update the H1 header** to match the new filename number exactly.
3. **Grep all other `plan/*.md`** for references to the old number (e.g. "Chunk 2.4", "Requires 4.1") and update those too.
4. **If Status is "Done"**, verify the claimed file(s) actually exist and are non-stub before trusting the label.
5. **Never leave 0-byte or duplicate-content files in `plan/`** — either finish them or delete before committing.
