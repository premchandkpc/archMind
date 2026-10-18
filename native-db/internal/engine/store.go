package engine

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"sync"
	"time"
)

const (
	maxRecordBytes = 16 << 20
	headerBytes    = 4
	checksumBytes  = sha256.Size
)

var (
	ErrClosed       = errors.New("database is closed")
	ErrPoisoned     = errors.New("database has an uncertain WAL write; reopen it")
	ErrCorruptWAL   = errors.New("corrupt WAL")
	ErrNotFound     = errors.New("record not found")
	ErrInvalidInput = errors.New("invalid input")
)

type recordType string

const (
	recordUpsertChunk    recordType = "upsert_chunk"
	recordDeleteChunk    recordType = "delete_chunk"
	recordUpsertEvidence recordType = "upsert_evidence"
)

type walRecord struct {
	Sequence int64      `json:"sequence"`
	Type     recordType `json:"type"`
	Chunk    *Chunk     `json:"chunk,omitempty"`
	ChunkID  string     `json:"chunk_id,omitempty"`
	Evidence *Evidence  `json:"evidence,omitempty"`
}

// Store is safe for concurrent goroutines in one process. Multi-process file
// locking and distributed replication are intentionally out of scope for v0.
type Store struct {
	mu       sync.RWMutex
	dir      string
	walPath  string
	wal      *os.File
	chunks   map[string]Chunk
	evidence map[string]Evidence
	index    *searchIndex
	sequence int64
	closed   bool
	poisoned bool
}

// Open opens or creates a database directory and replays the WAL.
func Open(dir string) (*Store, error) {
	if dir == "" {
		return nil, fmt.Errorf("%w: data directory is required", ErrInvalidInput)
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, fmt.Errorf("create database directory: %w", err)
	}
	s := &Store{
		dir:      dir,
		walPath:  filepath.Join(dir, "civilmind.wal"),
		chunks:   make(map[string]Chunk),
		evidence: make(map[string]Evidence),
		index:    newSearchIndex(),
	}
	if err := s.replay(); err != nil {
		return nil, err
	}
	wal, err := os.OpenFile(s.walPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		return nil, fmt.Errorf("open WAL for append: %w", err)
	}
	s.wal = wal
	return s, nil
}

// Sequence returns the last committed log sequence.
func (s *Store) Sequence() int64 {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.sequence
}

// Count returns the number of currently live chunks.
func (s *Store) Count() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.chunks)
}

// UpsertChunk validates and durably stores a chunk before exposing it to readers.
func (s *Store) UpsertChunk(chunk Chunk) (int64, error) {
	if err := validateChunk(chunk); err != nil {
		return 0, err
	}
	chunk = cloneChunk(chunk)
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.ensureOpen(); err != nil {
		return 0, err
	}

	dimensions := 0
	for id, current := range s.chunks {
		if id != chunk.ID && len(current.Vector) > 0 {
			if dimensions != 0 && dimensions != len(current.Vector) {
				return 0, fmt.Errorf("%w: inconsistent stored vector dimensions", ErrCorruptWAL)
			}
			dimensions = len(current.Vector)
		}
	}
	if len(chunk.Vector) > 0 && dimensions > 0 && len(chunk.Vector) != dimensions {
		return 0, fmt.Errorf("%w: vector dimension must be %d", ErrInvalidInput, dimensions)
	}

	seq, err := s.append(walRecord{Type: recordUpsertChunk, Chunk: &chunk})
	if err != nil {
		return 0, err
	}
	s.applyChunk(chunk)
	s.sequence = seq
	return seq, nil
}

// DeleteChunk writes a tombstone. Deleting the same ID more than once is safe.
func (s *Store) DeleteChunk(id string) (int64, error) {
	if id == "" {
		return 0, fmt.Errorf("%w: chunk id is required", ErrInvalidInput)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.ensureOpen(); err != nil {
		return 0, err
	}
	seq, err := s.append(walRecord{Type: recordDeleteChunk, ChunkID: id})
	if err != nil {
		return 0, err
	}
	s.applyDelete(id)
	s.sequence = seq
	return seq, nil
}

// GetChunk fetches a copy of a chunk by stable ID.
func (s *Store) GetChunk(id string) (Chunk, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	chunk, ok := s.chunks[id]
	if !ok {
		return Chunk{}, false
	}
	return cloneChunk(chunk), true
}

// PutEvidence durably stores a source reference for an existing chunk.
func (s *Store) PutEvidence(item Evidence) (int64, error) {
	if item.ID == "" || item.ChunkID == "" || item.Source == "" || item.Page < 0 {
		return 0, fmt.Errorf("%w: evidence id, chunk_id, source and non-negative page are required", ErrInvalidInput)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.ensureOpen(); err != nil {
		return 0, err
	}
	if _, ok := s.chunks[item.ChunkID]; !ok {
		return 0, fmt.Errorf("%w: evidence chunk %q", ErrNotFound, item.ChunkID)
	}
	if item.CreatedAt.IsZero() {
		item.CreatedAt = time.Now().UTC()
	}
	seq, err := s.append(walRecord{Type: recordUpsertEvidence, Evidence: &item})
	if err != nil {
		return 0, err
	}
	s.evidence[item.ID] = item
	s.sequence = seq
	return seq, nil
}

// EvidenceForChunk returns evidence sorted by page and ID for deterministic APIs.
func (s *Store) EvidenceForChunk(chunkID string) []Evidence {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]Evidence, 0)
	for _, item := range s.evidence {
		if item.ChunkID == chunkID {
			out = append(out, item)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Page == out[j].Page {
			return out[i].ID < out[j].ID
		}
		return out[i].Page < out[j].Page
	})
	return out
}

// Search returns hybrid BM25 + exact-cosine matches, fused with reciprocal rank fusion.
func (s *Store) Search(options SearchOptions) ([]Hit, error) {
	if options.ProjectID == "" {
		return nil, fmt.Errorf("%w: project_id is required", ErrInvalidInput)
	}
	if options.Query == "" && len(options.QueryVector) == 0 {
		return nil, fmt.Errorf("%w: query or query_vector is required", ErrInvalidInput)
	}
	limit := options.Limit
	if limit == 0 {
		limit = 10
	}
	if limit < 1 || limit > 100 {
		return nil, fmt.Errorf("%w: limit must be between 1 and 100", ErrInvalidInput)
	}
	rrfK := options.RRFK
	if rrfK == 0 {
		rrfK = 60
	}
	if rrfK < 1 {
		return nil, fmt.Errorf("%w: rrf_k must be positive", ErrInvalidInput)
	}
	if len(options.QueryVector) > 0 {
		if err := validateVector(options.QueryVector); err != nil {
			return nil, err
		}
	}

	s.mu.RLock()
	defer s.mu.RUnlock()
	if err := s.ensureOpen(); err != nil {
		return nil, err
	}
	allowed := make(map[string]struct{})
	for id, chunk := range s.chunks {
		if chunk.ProjectID == options.ProjectID && matchesMetadata(chunk.Metadata, options.MetadataFilter) {
			allowed[id] = struct{}{}
		}
	}
	poolSize := limit * 5
	if poolSize < 20 {
		poolSize = 20
	}
	if poolSize > 200 {
		poolSize = 200
	}
	var lexical []lexicalHit
	if options.Query != "" {
		lexical = s.index.lexicalSearch(options.Query, allowed, poolSize)
	}
	var vector []lexicalHit
	var err error
	if len(options.QueryVector) > 0 {
		vector, err = s.index.vectorSearch(options.QueryVector, allowed, poolSize)
		if err != nil {
			return nil, err
		}
	}

	lexicalRanks := make(map[string]int, len(lexical))
	lexicalScores := make(map[string]float64, len(lexical))
	for rank, hit := range lexical {
		lexicalRanks[hit.id] = rank + 1
		lexicalScores[hit.id] = hit.score
	}
	vectorRanks := make(map[string]int, len(vector))
	vectorScores := make(map[string]float64, len(vector))
	for rank, hit := range vector {
		vectorRanks[hit.id] = rank + 1
		vectorScores[hit.id] = hit.score
	}
	ids := make(map[string]struct{}, len(lexicalRanks)+len(vectorRanks))
	for id := range lexicalRanks {
		ids[id] = struct{}{}
	}
	for id := range vectorRanks {
		ids[id] = struct{}{}
	}
	hits := make([]Hit, 0, len(ids))
	for id := range ids {
		lr, vr := lexicalRanks[id], vectorRanks[id]
		score := 0.0
		if lr > 0 {
			score += 1.0 / float64(rrfK+lr)
		}
		if vr > 0 {
			score += 1.0 / float64(rrfK+vr)
		}
		var vectorScore *float64
		if scoreValue, ok := vectorScores[id]; ok {
			value := scoreValue
			vectorScore = &value
		}
		hits = append(hits, Hit{
			Chunk: cloneChunk(s.chunks[id]), Score: score,
			LexicalScore: lexicalScores[id], VectorScore: vectorScore,
			LexicalRank: lr, VectorRank: vr,
		})
	}
	sort.Slice(hits, func(i, j int) bool {
		if hits[i].Score == hits[j].Score {
			return hits[i].Chunk.ID < hits[j].Chunk.ID
		}
		return hits[i].Score > hits[j].Score
	})
	if len(hits) > limit {
		hits = hits[:limit]
	}
	return hits, nil
}

// Stats reports essential state for health checks and operational diagnostics.
func (s *Store) Stats() (map[string]any, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if err := s.ensureOpen(); err != nil {
		return nil, err
	}
	info, err := os.Stat(s.walPath)
	if err != nil {
		return nil, fmt.Errorf("stat WAL: %w", err)
	}
	return map[string]any{
		"engine": "civilmind-native-db", "format_version": 1,
		"sequence": s.sequence, "chunks": len(s.chunks),
		"evidence_records": len(s.evidence), "wal_bytes": info.Size(),
	}, nil
}

// Close flushes and closes the WAL. Repeated calls are safe.
func (s *Store) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return nil
	}
	s.closed = true
	if s.wal == nil {
		return nil
	}
	if err := s.wal.Sync(); err != nil {
		_ = s.wal.Close()
		return fmt.Errorf("sync WAL on close: %w", err)
	}
	if err := s.wal.Close(); err != nil {
		return fmt.Errorf("close WAL: %w", err)
	}
	return nil
}

func (s *Store) append(record walRecord) (int64, error) {
	if s.poisoned {
		return 0, ErrPoisoned
	}
	record.Sequence = s.sequence + 1
	payload, err := json.Marshal(record)
	if err != nil {
		return 0, fmt.Errorf("encode WAL record: %w", err)
	}
	if len(payload) == 0 || len(payload) > maxRecordBytes {
		return 0, fmt.Errorf("%w: WAL record size is invalid", ErrInvalidInput)
	}
	frame := make([]byte, headerBytes+len(payload)+checksumBytes)
	binary.BigEndian.PutUint32(frame[:headerBytes], uint32(len(payload)))
	copy(frame[headerBytes:], payload)
	sum := sha256.Sum256(payload)
	copy(frame[headerBytes+len(payload):], sum[:])
	for remaining := frame; len(remaining) > 0; {
		n, writeErr := s.wal.Write(remaining)
		if writeErr != nil {
			s.poisoned = true
			return 0, fmt.Errorf("append WAL: %w", writeErr)
		}
		if n == 0 {
			s.poisoned = true
			return 0, io.ErrShortWrite
		}
		remaining = remaining[n:]
	}
	if err := s.wal.Sync(); err != nil {
		s.poisoned = true
		return 0, fmt.Errorf("sync WAL: %w", err)
	}
	return record.Sequence, nil
}

func (s *Store) replay() error {
	wal, err := os.OpenFile(s.walPath, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return fmt.Errorf("open WAL for recovery: %w", err)
	}
	defer wal.Close()

	var validEnd int64
	var expectedSequence int64 = 1
	for {
		start, seekErr := wal.Seek(0, io.SeekCurrent)
		if seekErr != nil {
			return fmt.Errorf("read WAL offset: %w", seekErr)
		}
		var header [headerBytes]byte
		_, readErr := io.ReadFull(wal, header[:])
		if errors.Is(readErr, io.EOF) {
			validEnd = start
			break
		}
		if errors.Is(readErr, io.ErrUnexpectedEOF) {
			validEnd = start
			break
		}
		if readErr != nil {
			return fmt.Errorf("read WAL header: %w", readErr)
		}
		length := binary.BigEndian.Uint32(header[:])
		if length == 0 || length > maxRecordBytes {
			return fmt.Errorf("%w: invalid record length at offset %d", ErrCorruptWAL, start)
		}
		payload := make([]byte, int(length))
		if _, readErr = io.ReadFull(wal, payload); readErr != nil {
			if errors.Is(readErr, io.EOF) || errors.Is(readErr, io.ErrUnexpectedEOF) {
				validEnd = start
				break
			}
			return fmt.Errorf("read WAL payload: %w", readErr)
		}
		var digest [checksumBytes]byte
		if _, readErr = io.ReadFull(wal, digest[:]); readErr != nil {
			if errors.Is(readErr, io.EOF) || errors.Is(readErr, io.ErrUnexpectedEOF) {
				validEnd = start
				break
			}
			return fmt.Errorf("read WAL checksum: %w", readErr)
		}
		sum := sha256.Sum256(payload)
		if !equalBytes(sum[:], digest[:]) {
			return fmt.Errorf("%w: checksum mismatch at offset %d", ErrCorruptWAL, start)
		}
		var record walRecord
		if err := json.Unmarshal(payload, &record); err != nil {
			return fmt.Errorf("%w: invalid JSON at offset %d: %w", ErrCorruptWAL, start, err)
		}
		if record.Sequence != expectedSequence {
			return fmt.Errorf("%w: expected sequence %d at offset %d, got %d",
				ErrCorruptWAL, expectedSequence, start, record.Sequence)
		}
		if err := s.applyReplayRecord(record); err != nil {
			return fmt.Errorf("%w: sequence %d: %w", ErrCorruptWAL, record.Sequence, err)
		}
		s.sequence = record.Sequence
		expectedSequence++
		validEnd, _ = wal.Seek(0, io.SeekCurrent)
	}

	info, err := wal.Stat()
	if err != nil {
		return fmt.Errorf("stat WAL: %w", err)
	}
	if validEnd < info.Size() {
		if err := wal.Truncate(validEnd); err != nil {
			return fmt.Errorf("truncate incomplete WAL tail: %w", err)
		}
		if err := wal.Sync(); err != nil {
			return fmt.Errorf("sync repaired WAL: %w", err)
		}
	}
	dimensions := 0
	for _, chunk := range s.chunks {
		if len(chunk.Vector) == 0 {
			continue
		}
		if dimensions != 0 && dimensions != len(chunk.Vector) {
			return fmt.Errorf("%w: inconsistent vector dimensions after replay", ErrCorruptWAL)
		}
		dimensions = len(chunk.Vector)
	}
	s.index.rebuild(s.chunks)
	return nil
}

func (s *Store) applyReplayRecord(record walRecord) error {
	switch record.Type {
	case recordUpsertChunk:
		if record.Chunk == nil {
			return errors.New("upsert record is missing chunk")
		}
		if err := validateChunk(*record.Chunk); err != nil {
			return err
		}
		s.applyChunk(*record.Chunk)
	case recordDeleteChunk:
		if record.ChunkID == "" {
			return errors.New("delete record is missing chunk ID")
		}
		s.applyDelete(record.ChunkID)
	case recordUpsertEvidence:
		if record.Evidence == nil || record.Evidence.ID == "" || record.Evidence.ChunkID == "" ||
			record.Evidence.Source == "" || record.Evidence.Page < 0 {
			return errors.New("invalid evidence record")
		}
		if _, ok := s.chunks[record.Evidence.ChunkID]; !ok {
			return fmt.Errorf("evidence refers to missing chunk %q", record.Evidence.ChunkID)
		}
		s.evidence[record.Evidence.ID] = *record.Evidence
	default:
		return fmt.Errorf("unknown record type %q", record.Type)
	}
	return nil
}

func (s *Store) applyChunk(chunk Chunk) {
	chunk = cloneChunk(chunk)
	s.chunks[chunk.ID] = chunk
	s.index.upsert(chunk)
}

func (s *Store) applyDelete(id string) {
	delete(s.chunks, id)
	s.index.delete(id)
	for evidenceID, item := range s.evidence {
		if item.ChunkID == id {
			delete(s.evidence, evidenceID)
		}
	}
}

func (s *Store) ensureOpen() error {
	if s.closed {
		return ErrClosed
	}
	if s.poisoned {
		return ErrPoisoned
	}
	return nil
}

func validateChunk(chunk Chunk) error {
	if chunk.ID == "" || chunk.ProjectID == "" || chunk.DocumentID == "" ||
		chunk.RevisionID == "" || chunk.Content == "" {
		return fmt.Errorf("%w: id, project_id, document_id, revision_id and content are required",
			ErrInvalidInput)
	}
	if _, err := json.Marshal(chunk.Metadata); err != nil {
		return fmt.Errorf("%w: metadata must be JSON serializable: %v", ErrInvalidInput, err)
	}
	if len(chunk.Vector) > 0 {
		if err := validateVector(chunk.Vector); err != nil {
			return err
		}
	}
	return nil
}

func validateVector(vector []float64) error {
	if len(vector) == 0 {
		return fmt.Errorf("%w: vector must not be empty", ErrInvalidInput)
	}
	for _, value := range vector {
		if math.IsNaN(value) || math.IsInf(value, 0) {
			return fmt.Errorf("%w: vector values must be finite", ErrInvalidInput)
		}
	}
	if vectorNorm(vector) == 0 {
		return fmt.Errorf("%w: vector must not be zero", ErrInvalidInput)
	}
	return nil
}

func vectorNorm(vector []float64) float64 {
	sum := 0.0
	for _, value := range vector {
		sum += value * value
	}
	return math.Sqrt(sum)
}

func cloneChunk(chunk Chunk) Chunk {
	cloned := chunk
	cloned.Vector = append([]float64(nil), chunk.Vector...)
	if chunk.Metadata != nil {
		raw, err := json.Marshal(chunk.Metadata)
		if err == nil {
			var metadata map[string]any
			if json.Unmarshal(raw, &metadata) == nil {
				cloned.Metadata = metadata
			}
		}
	}
	return cloned
}

func matchesMetadata(metadata, filters map[string]any) bool {
	for key, expected := range filters {
		actual, exists := metadata[key]
		if !exists {
			return false
		}
		// Compare JSON-normalized values so int(2) and JSON's float64(2)
		// behave identically, including nested objects and arrays.
		raw, err := json.Marshal(expected)
		if err != nil {
			return false
		}
		var normalized any
		if err := json.Unmarshal(raw, &normalized); err != nil {
			return false
		}
		if !reflect.DeepEqual(actual, normalized) {
			return false
		}
	}
	return true
}

func equalBytes(left, right []byte) bool {
	if len(left) != len(right) {
		return false
	}
	var diff byte
	for i := range left {
		diff |= left[i] ^ right[i]
	}
	return diff == 0
}
