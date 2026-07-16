# ============================================================
# CivilMind AI — Makefile
# Usage: make <target>
# ============================================================

.PHONY: help install install-dev clean lint format typecheck test test-unit test-live
.PHONY: run run-dev run-worker db-migrate db-migrate-new db-down db-current db-history
.PHONY: docker-up docker-down docker-down-volumes docker-ps docker-logs docker-restart
.PHONY: docker-postgres docker-qdrant docker-minio docker-neo4j docker-redis
.PHONY: health check-all build build-docker
.PHONY: setup quickstart env

# ---------- Config ----------
PYTHON := .venv/bin/python
PIP    := .venv/bin/pip
UV     := uv
APP    := civilmind.api.app:app
HOST   := 0.0.0.0
PORT   := 8000
WORKERS := 1

# ============================================================
# HELP
# ============================================================

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ============================================================
# SETUP
# ============================================================

env: ## Create .env from .env.example (if not exists)
	@test -f .env || (cp .env.example .env && echo "Created .env — edit it with your API keys")
	@test -f .env && echo ".env exists"

setup: env ## Full setup: venv + deps + env
	$(UV) venv .venv
	$(UV) pip install -e ".[dev]"
	@echo ""
	@echo "Setup complete. Edit .env, then run: make docker-up && make db-migrate && make run"

quickstart: setup docker-up db-migrate ## One-command setup: install + services + migrate
	@echo ""
	@echo "Ready! Run: make run"

# ============================================================
# INSTALL
# ============================================================

install: ## Install production dependencies
	$(UV) venv .venv
	$(UV) pip install -e "."

install-dev: ## Install all dependencies (production + dev)
	$(UV) venv .venv
	$(UV) pip install -e ".[dev]"

clean: ## Remove build artifacts and caches
	rm -rf .venv/ dist/ build/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned"

# ============================================================
# LINT / FORMAT / TYPECHECK
# ============================================================

lint: ## Run ruff linter
	$(PYTHON) -m ruff check civilmind/ tests/

format: ## Auto-format code with ruff
	$(PYTHON) -m ruff format civilmind/ tests/
	$(PYTHON) -m ruff check --fix civilmind/ tests/

typecheck: ## Run mypy type checker
	$(PYTHON) -m mypy civilmind/

# ============================================================
# TEST
# ============================================================

test: ## Run all tests
	$(PYTHON) -m pytest tests/ -v

test-unit: ## Run unit tests only (no live services)
	$(PYTHON) -m pytest tests/ -v --ignore=tests/live

test-live: ## Run live integration tests (requires Docker services)
	$(PYTHON) -c "from civilmind.api.app import create_app; \
		from fastapi.testclient import TestClient; \
		r = TestClient(create_app()).get('/health'); \
		print(r.json())"

test-tools: ## Test tool registry and base classes
	$(PYTHON) -m pytest tests/ -v -k "tool" 2>/dev/null || \
	$(PYTHON) -c "\
	from civilmind.tools.base import BaseTool, ToolResult; \
	from civilmind.tools.registry import ToolRegistry; \
	class T(BaseTool): \
	    name='t'; description='t'; category='test'; \
	    async def execute(self, **kw): return ToolResult(success=True); \
	r = ToolRegistry(); r.register(T()); \
	assert r.has('t'); assert len(r.list_tools()) == 1; \
	print('[OK] Tool registry works')"

# ============================================================
# RUN
# ============================================================

run: ## Run API server (production)
	$(PYTHON) -m uvicorn $(APP) --host $(HOST) --port $(PORT) --workers $(WORKERS)

run-dev: ## Run API server (dev mode with auto-reload)
	$(PYTHON) -m uvicorn $(APP) --host $(HOST) --port $(PORT) --reload

run-worker: ## Run background worker (ingestion pipeline)
	@echo "Worker not implemented yet (Phase 3.4)"

# ============================================================
# DATABASE
# ============================================================

db-migrate: ## Apply all pending migrations
	$(PYTHON) -m alembic upgrade head

db-migrate-new: ## Create new migration (usage: make db-migrate-new MSG="add index")
	$(PYTHON) -m alembic revision --autogenerate -m "$(MSG)"

db-down: ## Rollback one migration
	$(PYTHON) -m alembic downgrade -1

db-current: ## Show current migration version
	$(PYTHON) -m alembic current

db-history: ## Show migration history
	$(PYTHON) -m alembic history

db-reset: ## DANGEROUS: drop all tables and re-migrate
	$(PYTHON) -c "\
	import asyncio, asyncpg; \
	async def reset(): \
	    c = await asyncpg.connect('postgresql://civilmind:civilmind@localhost:5432/civilmind'); \
	    await c.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public'); \
	    await c.close(); \
	    print('Schema dropped'); \
	asyncio.run(reset())"
	$(PYTHON) -m alembic upgrade head
	@echo "Database reset complete"

# ============================================================
# DOCKER — ALL SERVICES
# ============================================================

docker-up: ## Start all Docker services
	@echo "Starting PostgreSQL..."
	@docker run -d --name civilmind-postgres -p 5432:5432 \
		-e POSTGRES_USER=civilmind -e POSTGRES_PASSWORD=civilmind -e POSTGRES_DB=civilmind \
		-v civilmind-postgres-data:/var/lib/postgresql/data \
		--restart unless-stopped postgres:16-alpine 2>/dev/null || docker start civilmind-postgres
	@echo "Starting Qdrant..."
	@docker run -d --name civilmind-qdrant -p 6333:6333 -p 6334:6334 \
		-v civilmind-qdrant-data:/qdrant/storage \
		--restart unless-stopped qdrant/qdrant 2>/dev/null || docker start civilmind-qdrant
	@echo "Starting MinIO..."
	@docker run -d --name civilmind-minio -p 9000:9000 -p 9001:9001 \
		-e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin \
		-v civilmind-minio-data:/data \
		--restart unless-stopped minio/minio server /data --console-address ":9001" 2>/dev/null || docker start civilmind-minio
	@echo "Starting Neo4j..."
	@docker run -d --name civilmind-neo4j -p 7474:7474 -p 7687:7687 \
		-e NEO4J_AUTH=neo4j/password -e NEO4J_PLUGINS='["apoc"]' \
		-v civilmind-neo4j-data:/data \
		--restart unless-stopped neo4j:5-community 2>/dev/null || docker start civilmind-neo4j
	@echo "Starting Redis..."
	@docker run -d --name civilmind-redis -p 6379:6379 \
		-v civilmind-redis-data:/data \
		--restart unless-stopped redis:7-alpine redis-server --appendonly yes 2>/dev/null || docker start civilmind-redis
	@echo ""
	@echo "All services started. Run 'make docker-ps' to check."

docker-down: ## Stop all Docker services
	@docker stop civilmind-postgres civilmind-qdrant civilmind-minio civilmind-neo4j civilmind-redis 2>/dev/null || true
	@echo "All services stopped"

docker-down-volumes: ## Stop and remove all data (DANGEROUS)
	@docker stop civilmind-postgres civilmind-qdrant civilmind-minio civilmind-neo4j civilmind-redis 2>/dev/null || true
	@docker rm -v civilmind-postgres civilmind-qdrant civilmind-minio civilmind-neo4j civilmind-redis 2>/dev/null || true
	@echo "All containers and volumes removed"

docker-ps: ## Show running containers
	@docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep civilmind || echo "No civilmind containers running"

docker-logs: ## Tail logs from all services (Ctrl+C to stop)
	@docker logs -f civilmind-postgres --tail 5 &
	@docker logs -f civilmind-qdrant --tail 5 &
	@docker logs -f civilmind-minio --tail 5 &
	@docker logs -f civilmind-neo4j --tail 5 &
	@docker logs -f civilmind-redis --tail 5 &
	@wait

docker-restart: docker-down docker-up ## Restart all services

# ============================================================
# DOCKER — INDIVIDUAL SERVICES
# ============================================================

docker-postgres: ## Start PostgreSQL only
	@docker run -d --name civilmind-postgres -p 5432:5432 \
		-e POSTGRES_USER=civilmind -e POSTGRES_PASSWORD=civilmind -e POSTGRES_DB=civilmind \
		-v civilmind-postgres-data:/var/lib/postgresql/data \
		--restart unless-stopped postgres:16-alpine 2>/dev/null || docker start civilmind-postgres

docker-qdrant: ## Start Qdrant only
	@docker run -d --name civilmind-qdrant -p 6333:6333 -p 6334:6334 \
		-v civilmind-qdrant-data:/qdrant/storage \
		--restart unless-stopped qdrant/qdrant 2>/dev/null || docker start civilmind-qdrant

docker-minio: ## Start MinIO only
	@docker run -d --name civilmind-minio -p 9000:9000 -p 9001:9001 \
		-e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin \
		-v civilmind-minio-data:/data \
		--restart unless-stopped minio/minio server /data --console-address ":9001" 2>/dev/null || docker start civilmind-minio

docker-neo4j: ## Start Neo4j only
	@docker run -d --name civilmind-neo4j -p 7474:7474 -p 7687:7687 \
		-e NEO4J_AUTH=neo4j/password -e NEO4J_PLUGINS='["apoc"]' \
		-v civilmind-neo4j-data:/data \
		--restart unless-stopped neo4j:5-community 2>/dev/null || docker start civilmind-neo4j

docker-redis: ## Start Redis only
	@docker run -d --name civilmind-redis -p 6379:6379 \
		-v civilmind-redis-data:/data \
		--restart unless-stopped redis:7-alpine redis-server --appendonly yes 2>/dev/null || docker start civilmind-redis

# ============================================================
# CHECK / HEALTH
# ============================================================

health: ## Check all service connectivity
	@$(PYTHON) -c "\
	import asyncio, httpx; \
	async def check(): \
	    results = {}; \
	    import asyncpg; \
	    try: \
	        c = await asyncpg.connect('postgresql://civilmind:civilmind@localhost:5432/civilmind'); \
	        await c.execute('SELECT 1'); await c.close(); \
	        results['postgres'] = True \
	    except: results['postgres'] = False; \
	    async with httpx.AsyncClient() as h: \
	        r = await h.get('http://localhost:6333/healthz'); results['qdrant'] = r.status_code == 200; \
	        r = await h.get('http://localhost:9000/minio/health/live'); results['minio'] = r.status_code == 200; \
	    from neo4j import AsyncGraphDatabase; \
	    d = AsyncGraphDatabase.driver('bolt://localhost:7687', auth=('neo4j','password')); \
	    await d.verify_connectivity(); await d.close(); results['neo4j'] = True \
	    except: results['neo4j'] = False; \
	    import redis.asyncio as aioredis; \
	    r = aioredis.from_url('redis://localhost:6379/0'); await r.ping(); await r.aclose(); \
	    results['redis'] = True \
	    except: results['redis'] = False; \
	    return results; \
	r = asyncio.run(check()); \
	[print(f'  {\"[OK]\" if v else \"[--]\"} {k}') for k, v in r.items()]; \
	print(f'  All healthy: {all(r.values())}')"

check-all: health ## Alias for health
	@true

# ============================================================
# BUILD
# ============================================================

build: ## Build Python package
	$(PYTHON) -m build

build-docker: ## Build Docker image
	docker build -t civilmind:latest .

# ============================================================
# DOCKER COMPOSE (future)
# ============================================================

# Uncomment when docker-compose.yml is ready (Phase 10.3)
# compose-up: ## Start full stack with docker-compose
# 	docker compose up -d
# compose-down: ## Stop full stack
# 	docker compose down
# compose-logs: ## Tail all logs
# 	docker compose logs -f
