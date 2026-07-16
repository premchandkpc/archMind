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

## Project Conventions

- Python 3.11+, async throughout (FastAPI, SQLAlchemy async, redis.asyncio)
- Self-hosted infrastructure — no cloud dependencies
- Phase-by-phase incremental delivery
- Tools are swappable — agents never access DBs directly
- All tools return `ToolResult(success, data, error, latency_ms)`
- Tests must pass against live Docker services

## Files

- `Makefile` — all commands
- `pyproject.toml` — dependencies and tool config
- `Dockerfile` — app image
- `.env` — local config (gitignored)
- `civilmind/` — all application code
- `plan/` — phase completion tracking
