package engine

import "time"

// Chunk is a revision-aware CivilMind text fragment. Embeddings are produced by
// CivilMind's configured model; the database only stores and searches them.
type Chunk struct {
	ID         string         `json:"id"`
	ProjectID  string         `json:"project_id"`
	DocumentID string         `json:"document_id"`
	RevisionID string         `json:"revision_id"`
	Content    string         `json:"content"`
	Metadata   map[string]any `json:"metadata,omitempty"`
	Vector     []float64      `json:"vector,omitempty"`
}

// Evidence points a chunk back to its source artifact and location.
type Evidence struct {
	ID        string    `json:"id"`
	ChunkID   string    `json:"chunk_id"`
	Source    string    `json:"source"`
	Page      int       `json:"page,omitempty"`
	Text      string    `json:"text,omitempty"`
	CreatedAt time.Time `json:"created_at"`
}

// Hit exposes separate ranking contributions for explainable retrieval.
type Hit struct {
	Chunk        Chunk    `json:"chunk"`
	Score        float64  `json:"score"`
	LexicalScore float64  `json:"lexical_score"`
	VectorScore  *float64 `json:"vector_score,omitempty"`
	LexicalRank  int      `json:"lexical_rank,omitempty"`
	VectorRank   int      `json:"vector_rank,omitempty"`
}

// SearchOptions controls hybrid retrieval and exact metadata filtering.
type SearchOptions struct {
	Query          string         `json:"query"`
	ProjectID      string         `json:"project_id"`
	MetadataFilter map[string]any `json:"metadata_filter,omitempty"`
	QueryVector    []float64      `json:"query_vector,omitempty"`
	Limit          int            `json:"limit,omitempty"`
	RRFK           int            `json:"rrf_k,omitempty"`
}
