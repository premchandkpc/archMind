"""Append-only local store with checksummed records and crash-tail recovery.

The WAL is the source of truth. Search indexes are derived and rebuilt on startup.
This first version is a single-process, single-node embedded engine.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import threading
from pathlib import Path
from typing import Any

from civilmind.native_db.index import SearchIndex
from civilmind.native_db.models import Chunk, SearchHit

_HEADER = struct.Struct(">I")
_DIGEST_SIZE = hashlib.sha256().digest_size
_MAX_RECORD_BYTES = 16 * 1024 * 1024


class StoreError(RuntimeError):
    """Base class for storage-engine errors."""


class CorruptLogError(StoreError):
    """Raised when a complete WAL record fails integrity validation."""


class NativeStore:
    """Embedded retrieval DB with an fsynced WAL and rebuildable search indexes."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._wal_path = self.data_dir / "civilmind.wal"
        self._lock = threading.RLock()
        self._records: dict[str, Chunk] = {}
        self._index = SearchIndex()
        self._closed = False
        self._poisoned = False
        self._sequence = 0
        self._recover()

    @property
    def sequence(self) -> int:
        """Return the last committed/replayed sequence number."""
        return self._sequence

    @property
    def count(self) -> int:
        """Return the number of live chunks."""
        with self._lock:
            return len(self._records)

    def upsert(self, chunk: Chunk) -> int:
        """Durably insert or replace a chunk using its stable ID."""
        self._validate_chunk(chunk)
        with self._lock:
            self._ensure_usable()
            if chunk.vector is not None:
                dimensions = {
                    len(item.vector)
                    for item_id, item in self._records.items()
                    if item_id != chunk.id and item.vector is not None
                }
                if dimensions and len(chunk.vector) not in dimensions:
                    raise ValueError("vector dimension mismatch for this database")
            record = {
                "op": "upsert",
                "id": chunk.id,
                "chunk": {
                    "id": chunk.id, "project_id": chunk.project_id,
                    "document_id": chunk.document_id, "revision_id": chunk.revision_id,
                    "content": chunk.content, "metadata": chunk.metadata, "vector": chunk.vector,
                },
            }
            seq = self._append(record)
            self._records[chunk.id] = chunk
            self._index.upsert(chunk)
            self._sequence = seq
            return seq

    def delete(self, chunk_id: str) -> int:
        """Durably tombstone a chunk. Repeated deletes are safe."""
        if not chunk_id:
            raise ValueError("chunk_id must not be empty")
        with self._lock:
            self._ensure_usable()
            seq = self._append({"op": "delete", "id": chunk_id})
            self._records.pop(chunk_id, None)
            self._index.delete(chunk_id)
            self._sequence = seq
            return seq

    def get(self, chunk_id: str) -> Chunk | None:
        """Fetch a chunk by ID."""
        with self._lock:
            self._ensure_usable()
            return self._records.get(chunk_id)

    def search(
        self, query: str, *, project_id: str, metadata_filter: dict[str, Any] | None = None,
        query_vector: list[float] | None = None, limit: int = 10, rrf_k: int = 60,
    ) -> list[SearchHit]:
        """Run BM25 and optional exact-vector search, then fuse ranks with RRF."""
        if not project_id:
            raise ValueError("project_id is required")
        if not query.strip() and query_vector is None:
            raise ValueError("query or query_vector is required")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        if query_vector is not None and (not query_vector or any(not math.isfinite(v) for v in query_vector)):
            raise ValueError("query_vector must be non-empty and finite")
        with self._lock:
            self._ensure_usable()
            allowed = {
                chunk_id for chunk_id, chunk in self._records.items()
                if chunk.project_id == project_id and self._matches(chunk.metadata, metadata_filter or {})
            }
            pool_size = min(max(limit * 5, 20), 200)
            lexical = self._index.lexical_search(query, allowed, pool_size) if query.strip() else []
            vector = self._index.vector_search(query_vector, allowed, pool_size) if query_vector is not None else []
            lexical_ranks = {hit.chunk_id: rank for rank, hit in enumerate(lexical, start=1)}
            lexical_scores = {hit.chunk_id: hit.score for hit in lexical}
            vector_ranks = {chunk_id: rank for rank, (chunk_id, _) in enumerate(vector, start=1)}
            vector_scores = dict(vector)
            fused: list[SearchHit] = []
            for chunk_id in set(lexical_ranks) | set(vector_ranks):
                lr, vr = lexical_ranks.get(chunk_id), vector_ranks.get(chunk_id)
                score = (1.0 / (rrf_k + lr) if lr is not None else 0.0) + (1.0 / (rrf_k + vr) if vr is not None else 0.0)
                fused.append(SearchHit(
                    chunk=self._records[chunk_id], score=score,
                    lexical_score=lexical_scores.get(chunk_id, 0.0),
                    vector_score=vector_scores.get(chunk_id), lexical_rank=lr, vector_rank=vr,
                ))
            fused.sort(key=lambda hit: (-hit.score, hit.chunk.id))
            return fused[:limit]

    def stats(self) -> dict[str, int | str]:
        """Return basic storage-engine diagnostics."""
        with self._lock:
            return {"engine": "civilmind-native-db", "format_version": 1,
                    "sequence": self._sequence, "chunks": len(self._records),
                    "wal_bytes": self._wal_path.stat().st_size if self._wal_path.exists() else 0}

    def close(self) -> None:
        """Close this instance to future operations."""
        with self._lock:
            self._closed = True

    def _append(self, record: dict[str, Any]) -> int:
        seq = self._sequence + 1
        payload = json.dumps({"seq": seq, **record}, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(payload) > _MAX_RECORD_BYTES:
            raise ValueError(f"WAL record exceeds {_MAX_RECORD_BYTES} bytes")
        frame = _HEADER.pack(len(payload)) + payload + hashlib.sha256(payload).digest()
        try:
            with self._wal_path.open("ab", buffering=0) as wal:
                view = memoryview(frame)
                while view:
                    written = wal.write(view)
                    if written is None or written <= 0:
                        raise OSError("short write while appending WAL")
                    view = view[written:]
                os.fsync(wal.fileno())
        except OSError:
            self._poisoned = True
            raise
        return seq

    def _recover(self) -> None:
        if not self._wal_path.exists():
            self._wal_path.touch()
            return
        valid_end = 0
        records: list[dict[str, Any]] = []
        with self._wal_path.open("rb") as wal:
            while True:
                start = wal.tell()
                header = wal.read(_HEADER.size)
                if not header:
                    valid_end = start
                    break
                if len(header) < _HEADER.size:
                    valid_end = start
                    break
                (size,) = _HEADER.unpack(header)
                if size == 0 or size > _MAX_RECORD_BYTES:
                    raise CorruptLogError(f"invalid WAL record length at byte {start}")
                payload, digest = wal.read(size), wal.read(_DIGEST_SIZE)
                if len(payload) < size or len(digest) < _DIGEST_SIZE:
                    valid_end = start
                    break
                if hashlib.sha256(payload).digest() != digest:
                    raise CorruptLogError(f"WAL checksum mismatch at byte {start}")
                try:
                    record = json.loads(payload)
                except json.JSONDecodeError as exc:
                    raise CorruptLogError(f"invalid WAL JSON at byte {start}") from exc
                expected = len(records) + 1
                if record.get("seq") != expected:
                    raise CorruptLogError(f"WAL sequence gap at byte {start}: expected {expected}, got {record.get('seq')}")
                records.append(record)
                valid_end = wal.tell()
        actual_size = self._wal_path.stat().st_size
        if valid_end < actual_size:
            with self._wal_path.open("r+b") as wal:
                wal.truncate(valid_end)
                wal.flush()
                os.fsync(wal.fileno())
        for record in records:
            if record.get("op") == "upsert":
                data = record.get("chunk")
                if not isinstance(data, dict):
                    raise CorruptLogError(f"missing chunk at sequence {record['seq']}")
                chunk = self._decode_chunk(data)
                self._records[chunk.id] = chunk
            elif record.get("op") == "delete":
                self._records.pop(str(record.get("id", "")), None)
            else:
                raise CorruptLogError(f"unknown WAL operation at sequence {record['seq']}")
            self._sequence = int(record["seq"])
        dimensions = {len(item.vector) for item in self._records.values() if item.vector is not None}
        if len(dimensions) > 1:
            raise CorruptLogError("stored vectors have inconsistent dimensions")
        self._index.replace_all(self._records.values())

    @staticmethod
    def _decode_chunk(data: dict[str, Any]) -> Chunk:
        try:
            return Chunk(id=str(data["id"]), project_id=str(data["project_id"]),
                         document_id=str(data["document_id"]), revision_id=str(data["revision_id"]),
                         content=str(data["content"]), metadata=dict(data.get("metadata") or {}),
                         vector=[float(v) for v in data["vector"]] if data.get("vector") is not None else None)
        except (KeyError, TypeError, ValueError) as exc:
            raise CorruptLogError("invalid chunk record in WAL") from exc

    @staticmethod
    def _validate_chunk(chunk: Chunk) -> None:
        if not all(isinstance(value, str) and value.strip() for value in
                   (chunk.id, chunk.project_id, chunk.document_id, chunk.revision_id, chunk.content)):
            raise ValueError("id, project_id, document_id, revision_id and content are required")
        if not isinstance(chunk.metadata, dict):
            raise ValueError("metadata must be a JSON object")
        try:
            json.dumps(chunk.metadata, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be JSON-serializable and finite") from exc
        if chunk.vector is not None:
            if not chunk.vector or any(not math.isfinite(value) for value in chunk.vector):
                raise ValueError("vector must be non-empty and finite")
            if math.sqrt(sum(value * value for value in chunk.vector)) == 0:
                raise ValueError("vector must not be a zero vector")

    @staticmethod
    def _matches(metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
        return all(metadata.get(key) == value for key, value in filters.items())

    def _ensure_usable(self) -> None:
        if self._closed:
            raise StoreError("store is closed")
        if self._poisoned:
            raise StoreError("store is poisoned after an uncertain WAL write; reopen it")
