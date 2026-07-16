"""Application configuration constants.

Design decisions live here — changing these values requires engineer review.
Deployment facts (DB hosts, API keys) belong in settings.py.
"""

from civilmind.settings import settings

APP_NAME = settings.APP_NAME
APP_VERSION = "0.1.0"

# Supported document types — from settings (env configurable)
SUPPORTED_FORMATS = settings.SUPPORTED_FORMATS

# Embedding dimensions — from settings (env configurable)
EMBEDDING_DIMS = settings.EMBEDDING_DIMS


def get_embedding_dim(model_name: str) -> int:
    """Look up embedding dimension for a model. Fails loud if model is unknown."""
    if model_name not in EMBEDDING_DIMS:
        raise ValueError(
            f"Unknown embedding model '{model_name}'. "
            f"Add its dimension to EMBEDDING_DIMS_CSV in .env."
        )
    return EMBEDDING_DIMS[model_name]


# Vector DB
DEFAULT_COLLECTION = "civilmind"

# Chunking
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
SEMANTIC_THRESHOLD = 0.5

# Retrieval
BM25_TOP_K = 20
VECTOR_TOP_K = 20
RRF_MERGE_TOP_K = 30
RERANK_TOP_K = 10
FINAL_TOP_K = 5

# Minimum corpus size to enable BM25 (below this, pure vector search)
MIN_CORPUS_FOR_BM25 = 50

# Workflow
MAX_ITERATIONS = 3
