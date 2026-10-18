"""Correctness and recovery tests for the CivilMind native database."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from civilmind.native_db import Chunk, NativeStore
from civilmind.native_db.store import CorruptLogError

_HEADER = struct.Struct(">I")


def make_chunk(
    chunk_id: str, content: str, *, project: str = "p1", vector: list[float] | None = None,
    metadata: dict | None = None,
) -> Chunk:
    return Chunk(id=chunk_id, project_id=project, document_id=f"doc-{chunk_id}",
                 revision_id="rev-1", content=content, metadata=metadata or {}, vector=vector)


def test_wal_persists_and_replays_upserts_and_deletes(tmp_path: Path) -> None:
    store = NativeStore(tmp_path)
    store.upsert(make_chunk("a", "IS 456 concrete grade", vector=[1.0, 0.0]))
    store.upsert(make_chunk("b", "plumbing pipe clearance", vector=[0.0, 1.0]))
    store.upsert(make_chunk("a", "updated IS 456 column detail", vector=[0.9, 0.1]))
    store.delete("b")
    assert store.count == 1
    store.close()
    reopened = NativeStore(tmp_path)
    assert reopened.count == 1
    assert reopened.sequence == 4
    assert reopened.get("a") is not None
    assert reopened.get("a").content == "updated IS 456 column detail"
    assert reopened.get("b") is None


def test_search_uses_lexical_vector_and_metadata_filters(tmp_path: Path) -> None:
    store = NativeStore(tmp_path)
    store.upsert(make_chunk("a", "IS 456 minimum concrete grade", vector=[1.0, 0.0],
                            metadata={"discipline": "structural"}))
    store.upsert(make_chunk("b", "pipe routing and clearance", vector=[0.0, 1.0],
                            metadata={"discipline": "mep"}))
    store.upsert(make_chunk("c", "concrete column reinforcement", project="p2",
                            vector=[0.8, 0.2], metadata={"discipline": "structural"}))
    hits = store.search("IS 456 concrete", project_id="p1",
                        metadata_filter={"discipline": "structural"},
                        query_vector=[1.0, 0.0], limit=5)
    assert [hit.chunk.id for hit in hits] == ["a"]
    assert hits[0].lexical_rank == 1
    assert hits[0].vector_rank == 1


def test_lexical_search_preserves_engineering_codes(tmp_path: Path) -> None:
    store = NativeStore(tmp_path)
    store.upsert(make_chunk("a", "See IS:456 clause 5.3 for concrete"))
    store.upsert(make_chunk("b", "General concrete guidance"))
    hits = store.search("IS:456 5.3", project_id="p1")
    assert hits
    assert hits[0].chunk.id == "a"


def test_torn_final_record_is_truncated(tmp_path: Path) -> None:
    store = NativeStore(tmp_path)
    store.upsert(make_chunk("a", "first"))
    store.close()
    wal_path = tmp_path / "civilmind.wal"
    with wal_path.open("ab") as wal:
        wal.write(_HEADER.pack(100) + b'{"seq":2')
    reopened = NativeStore(tmp_path)
    assert reopened.count == 1
    assert reopened.sequence == 1


def test_complete_bad_checksum_is_not_silently_discarded(tmp_path: Path) -> None:
    store = NativeStore(tmp_path)
    store.upsert(make_chunk("a", "first"))
    store.close()
    wal_path = tmp_path / "civilmind.wal"
    raw = wal_path.read_bytes()
    length = _HEADER.unpack(raw[:4])[0]
    payload = raw[4 : 4 + length]
    damaged = bytearray(payload)
    damaged[-1] ^= 1
    wal_path.write_bytes(_HEADER.pack(length) + damaged + hashlib.sha256(payload).digest())
    with pytest.raises(CorruptLogError, match="checksum"):
        NativeStore(tmp_path)


def test_invalid_vectors_rejected_without_commit(tmp_path: Path) -> None:
    store = NativeStore(tmp_path)
    with pytest.raises(ValueError, match="zero vector"):
        store.upsert(make_chunk("a", "text", vector=[0.0, 0.0]))
    assert store.sequence == 0
    assert store.count == 0


def test_cross_project_search_isolation(tmp_path: Path) -> None:
    store = NativeStore(tmp_path)
    store.upsert(make_chunk("a", "concrete grade", project="project-a"))
    store.upsert(make_chunk("b", "concrete grade", project="project-b"))
    hits = store.search("concrete", project_id="project-a")
    assert [hit.chunk.id for hit in hits] == ["a"]
