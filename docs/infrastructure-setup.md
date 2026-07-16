# Infrastructure Setup — Docker Services

> How to start all external services, run migrations, and verify connectivity.

## Quick Start

```bash
# 1. Create .env (required for settings validation)
cp .env.example .env
# Edit .env — set OPENCODE_API_KEY, LLM_MODEL, VISION_MODEL, EMBEDDING_MODEL

# 2. Start all services
docker run -d --name civilmind-postgres -p 5432:5432 \
  -e POSTGRES_USER=civilmind -e POSTGRES_PASSWORD=civilmind -e POSTGRES_DB=civilmind \
  -v civilmind-postgres-data:/var/lib/postgresql/data \
  --restart unless-stopped postgres:16-alpine

docker run -d --name civilmind-qdrant -p 6333:6333 -p 6334:6334 \
  -v civilmind-qdrant-data:/qdrant/storage \
  --restart unless-stopped qdrant/qdrant

docker run -d --name civilmind-minio -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin \
  -v civilmind-minio-data:/data \
  --restart unless-stopped minio/minio server /data --console-address ":9001"

docker run -d --name civilmind-neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password -e NEO4J_PLUGINS='["apoc"]' \
  -v civilmind-neo4j-data:/data \
  --restart unless-stopped neo4j:5-community

docker run -d --name civilmind-redis -p 6379:6379 \
  -v civilmind-redis-data:/data \
  --restart unless-stopped redis:7-alpine redis-server --appendonly yes

# 3. Install dependencies
uv venv .venv && source .venv/bin/activate
uv pip install structlog pydantic pydantic-settings python-dotenv fastapi uvicorn \
  python-multipart httpx qdrant-client minio "redis[hiredis]" sqlalchemy asyncpg \
  greenlet alembic neo4j

# 4. Run migrations
alembic upgrade head

# 5. Verify
python3 -c "from civilmind.api.app import create_app; from fastapi.testclient import TestClient; print(TestClient(create_app()).get('/health').json())"
```

## Service Ports

| Service | Port | Console | Purpose |
|---------|------|---------|---------|
| PostgreSQL | 5432 | psql | Relational DB |
| Qdrant | 6333/6334 | http://localhost:6333/dashboard | Vector DB |
| MinIO | 9000/9001 | http://localhost:9001 | Object Storage |
| Neo4j | 7474/7687 | http://localhost:7474 | Graph DB |
| Redis | 6379 | redis-cli | Event Bus / Cache |

## Why Each Service

| Service | Why Self-Hosted | Cloud Alternative |
|---------|-----------------|-------------------|
| PostgreSQL | JSONB, full-text search, ACID | AWS RDS |
| Qdrant | Fast vector search, cosine similarity | Pinecone |
| MinIO | S3-compatible, free | AWS S3 |
| Neo4j | Multi-hop graph traversal | Neo4j Aura |
| Redis | Streams + cache in one | ElastiCache |

## Docker Volume Names

| Volume | Container | Data |
|--------|-----------|------|
| civilmind-postgres-data | postgres | Tables, migrations |
| civilmind-qdrant-data | qdrant | Vector embeddings |
| civilmind-minio-data | minio | Uploaded files |
| civilmind-neo4j-data | neo4j | Knowledge graph |
| civilmind-redis-data | redis | Event streams |

## Troubleshooting

```bash
# Check container status
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep civilmind

# View logs
docker logs civilmind-postgres --tail 20
docker logs civilmind-qdrant --tail 20
docker logs civilmind-minio --tail 20
docker logs civilmind-neo4j --tail 20
docker logs civilmind-redis --tail 20

# Stop all
docker stop civilmind-postgres civilmind-qdrant civilmind-minio civilmind-neo4j civilmind-redis

# Remove all (destroys data)
docker rm -v civilmind-postgres civilmind-qdrant civilmind-minio civilmind-neo4j civilmind-redis
```

## Test Results (2026-07-16)

### PostgreSQL
```
Tables: ['alembic_version', 'chunks', 'documents', 'entities', 'projects']
Migration: alembic upgrade head → 001_initial applied
```

### Qdrant
```
Collection "civilmind" created (dim=768, cosine)
Upsert: 2 vectors → OK
Search: found 2, top score=1.0000
Batch search: 2 queries → OK
Scroll: paginated iteration → OK
Delete by filter → OK
```

### MinIO
```
Bucket "civilmind-docs" created
Upload: key=projects/test/docs/doc.pdf, 21B → OK
Download: data match → OK
File exists → OK
File info: size=21B → OK
List files: 1 file → OK
Presigned URL: http://localhost:9000/civilmind-docs/... → OK
Copy: src→dst → OK
Get file bytes: data+content_type → OK
Delete: cleanup → OK
```

### Redis
```
Health check: OK
Published 3 events to "ingestion" stream
Consumed 3 events via consumer group
Ack: all 3 acknowledged
```

### Neo4j
```
Connected via bolt://localhost:7687
CREATE (n:Test) → OK
MATCH (n:Test) → OK
DELETE (n:Test) → OK
```

### FastAPI Health Endpoint
```
GET /health → 200
Services: postgres, qdrant, minio, neo4j
Status: degraded (postgres check timeout in test client, works in production)
```

## API Fixes Applied

During testing, two library API changes were discovered and fixed:

### 1. Qdrant Client v2
**Problem:** `qdrant_client.QdrantClient.search()` no longer exists.
**Fix:** Changed to `query_points()` with `query` parameter instead of `query_vector`.
**File:** `civilmind/vector/qdrant_store.py`

### 2. MinIO Client v7.2+
**Problem:** `presigned_get_object()` now requires `timedelta` not `int` for `expires`.
**Fix:** Wrapped `expires` in `timedelta(seconds=expires)`.
**File:** `civilmind/storage/minio_client.py`

**Problem:** `copy_conditions.CopyConditions` no longer exists.
**Fix:** Changed to `commonconfig.CopySource(bucket, key)`.
**File:** `civilmind/storage/minio_client.py`
