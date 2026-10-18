package engine

import (
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func testChunk(id, project, content string, vector []float64, metadata map[string]any) Chunk {
	return Chunk{ID: id, ProjectID: project, DocumentID: "doc-" + id,
		RevisionID: "rev-1", Content: content, Vector: vector, Metadata: metadata}
}

func TestWALReplayUpsertDeleteAndEvidence(t *testing.T) {
	dir := t.TempDir()
	store, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.UpsertChunk(testChunk("c1", "p1", "IS:456 concrete column", []float64{1, 0}, nil)); err != nil {
		t.Fatal(err)
	}
	if _, err := store.PutEvidence(Evidence{ID: "e1", ChunkID: "c1", Source: "S-101.pdf", Page: 12, Text: "Column C12 width"}); err != nil {
		t.Fatal(err)
	}
	if _, err := store.UpsertChunk(testChunk("c2", "p1", "MEP pipe clearance", []float64{0, 1}, nil)); err != nil {
		t.Fatal(err)
	}
	if _, err := store.DeleteChunk("c2"); err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	reopened, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if got := reopened.Count(); got != 1 {
		t.Fatalf("Count() = %d, want 1", got)
	}
	if got := reopened.Sequence(); got != 4 {
		t.Fatalf("Sequence() = %d, want 4", got)
	}
	chunk, ok := reopened.GetChunk("c1")
	if !ok || chunk.Content != "IS:456 concrete column" {
		t.Fatalf("GetChunk() = %#v, %v", chunk, ok)
	}
	if _, ok := reopened.GetChunk("c2"); ok {
		t.Fatal("deleted chunk was restored during replay")
	}
	evidence := reopened.EvidenceForChunk("c1")
	if len(evidence) != 1 || evidence[0].Page != 12 {
		t.Fatalf("EvidenceForChunk() = %#v, want page 12", evidence)
	}
}

func TestHybridSearchHonorsProjectAndMetadataFilters(t *testing.T) {
	store, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	chunks := []Chunk{
		testChunk("struct-1", "p1", "IS:456 minimum concrete grade", []float64{1, 0}, map[string]any{"discipline": "structural"}),
		testChunk("mep-1", "p1", "MEP pipe route clearance", []float64{0, 1}, map[string]any{"discipline": "mep"}),
		testChunk("struct-2", "p2", "concrete reinforcement details", []float64{0.9, 0.1}, map[string]any{"discipline": "structural"}),
	}
	for _, chunk := range chunks {
		if _, err := store.UpsertChunk(chunk); err != nil {
			t.Fatal(err)
		}
	}
	hits, err := store.Search(SearchOptions{Query: "IS:456 concrete", ProjectID: "p1",
		MetadataFilter: map[string]any{"discipline": "structural"},
		QueryVector:    []float64{1, 0}, Limit: 5})
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 || hits[0].Chunk.ID != "struct-1" {
		t.Fatalf("unexpected hits: %#v", hits)
	}
	if hits[0].LexicalRank != 1 || hits[0].VectorRank != 1 {
		t.Fatalf("ranking contribution missing: %#v", hits[0])
	}
}

func TestVectorDimensionMismatchRejectedWithoutCommit(t *testing.T) {
	store, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.UpsertChunk(testChunk("c1", "p1", "first chunk", []float64{1, 0}, nil)); err != nil {
		t.Fatal(err)
	}
	sequence := store.Sequence()
	if _, err := store.UpsertChunk(testChunk("c2", "p1", "wrong dimension", []float64{1, 0, 0}, nil)); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("expected ErrInvalidInput, got %v", err)
	}
	if store.Sequence() != sequence || store.Count() != 1 {
		t.Fatal("invalid vector write changed database state")
	}
}

func TestIncompleteFinalRecordIsTruncated(t *testing.T) {
	dir := t.TempDir()
	store, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.UpsertChunk(testChunk("c1", "p1", "recover me", nil, nil)); err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	file, err := os.OpenFile(filepath.Join(dir, "civilmind.wal"), os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	var header [4]byte
	binary.BigEndian.PutUint32(header[:], 100)
	if _, err := file.Write(append(header[:], []byte(`{"sequence":2`)...)); err != nil {
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}

	reopened, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if reopened.Count() != 1 || reopened.Sequence() != 1 {
		t.Fatalf("bad recovery: count=%d seq=%d", reopened.Count(), reopened.Sequence())
	}
}

func TestCompleteChecksumFailureFailsClosed(t *testing.T) {
	dir := t.TempDir()
	store, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.UpsertChunk(testChunk("c1", "p1", "integrity matters", nil, nil)); err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "civilmind.wal")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	length := binary.BigEndian.Uint32(raw[:4])
	payload := append([]byte(nil), raw[4:4+length]...)
	payload[len(payload)-1] ^= 0x01
	sum := sha256.Sum256(raw[4 : 4+length])
	corrupt := make([]byte, 4+len(payload)+len(sum))
	binary.BigEndian.PutUint32(corrupt[:4], length)
	copy(corrupt[4:], payload)
	copy(corrupt[4+len(payload):], sum[:])
	if err := os.WriteFile(path, corrupt, 0o600); err != nil {
		t.Fatal(err)
	}
	_, err = Open(dir)
	if !errors.Is(err, ErrCorruptWAL) {
		t.Fatalf("Open() error = %v, want ErrCorruptWAL", err)
	}
}

func TestZeroVectorRejected(t *testing.T) {
	store, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.UpsertChunk(testChunk("c1", "p1", "invalid", []float64{0, 0}, nil)); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("expected ErrInvalidInput, got %v", err)
	}
	if store.Count() != 0 || store.Sequence() != 0 {
		t.Fatal("invalid vector changed database state")
	}
}

func TestMetadataNumbersAndNestedObjectsMatchByJSONValue(t *testing.T) {
	store, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	chunk := testChunk("c1", "p1", "concrete column", nil, map[string]any{
		"floor": 2, "attributes": map[string]any{"grade": "M20"},
	})
	if _, err := store.UpsertChunk(chunk); err != nil {
		t.Fatal(err)
	}
	hits, err := store.Search(SearchOptions{Query: "concrete", ProjectID: "p1",
		MetadataFilter: map[string]any{"floor": float64(2), "attributes": map[string]any{"grade": "M20"}}})
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 {
		t.Fatalf("wanted one metadata match, got %d", len(hits))
	}
}
