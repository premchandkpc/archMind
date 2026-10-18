package httpapi

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"strings"

	"github.com/premchandkpc/archMind/native-db/internal/engine"
)

const maxRequestBytes = 4 << 20

// Server exposes the embedded store as a small JSON HTTP service.
type Server struct {
	store *engine.Store
	token string
	mux   *http.ServeMux
}

// New constructs the HTTP handler. A blank token fails closed for all data APIs.
func New(store *engine.Store, token string) http.Handler {
	s := &Server{store: store, token: strings.TrimSpace(token), mux: http.NewServeMux()}
	s.routes()
	return requestLimits(s.mux)
}

func (s *Server) routes() {
	s.mux.HandleFunc("GET /health", s.health)
	s.mux.Handle("GET /v1/stats", s.authorize(http.HandlerFunc(s.stats)))
	s.mux.Handle("PUT /v1/chunks", s.authorize(http.HandlerFunc(s.putChunk)))
	s.mux.Handle("PUT /v1/chunks/batch", s.authorize(http.HandlerFunc(s.putChunks)))
	s.mux.Handle("DELETE /v1/chunks/{id}", s.authorize(http.HandlerFunc(s.deleteChunk)))
	s.mux.Handle("GET /v1/chunks/{id}", s.authorize(http.HandlerFunc(s.getChunk)))
	s.mux.Handle("POST /v1/search", s.authorize(http.HandlerFunc(s.search)))
	s.mux.Handle("POST /v1/evidence", s.authorize(http.HandlerFunc(s.putEvidence)))
	s.mux.Handle("GET /v1/chunks/{id}/evidence", s.authorize(http.HandlerFunc(s.getEvidence)))
}

func (s *Server) authorize(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if s.token == "" {
			writeError(w, http.StatusServiceUnavailable, "database API token is not configured")
			return
		}
		scheme, supplied, ok := strings.Cut(r.Header.Get("Authorization"), " ")
		if !ok || !strings.EqualFold(scheme, "Bearer") || supplied == "" ||
			len(supplied) != len(s.token) || !constantTimeEqual(supplied, s.token) {
			writeError(w, http.StatusUnauthorized, "invalid bearer token")
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	stats, err := s.store.Stats()
	if err != nil {
		writeError(w, http.StatusServiceUnavailable, "database is unavailable")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok", "database": stats})
}

func (s *Server) stats(w http.ResponseWriter, _ *http.Request) {
	stats, err := s.store.Stats()
	if err != nil {
		writeStoreError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, stats)
}

func (s *Server) putChunk(w http.ResponseWriter, r *http.Request) {
	var chunk engine.Chunk
	if err := decodeJSON(w, r, &chunk); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	sequence, err := s.store.UpsertChunk(chunk)
	if err != nil {
		writeStoreError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"id": chunk.ID, "sequence": sequence, "status": "committed",
	})
}

type chunkBatchRequest struct {
	Chunks []engine.Chunk `json:"chunks"`
}

func (s *Server) putChunks(w http.ResponseWriter, r *http.Request) {
	var payload chunkBatchRequest
	if err := decodeJSON(w, r, &payload); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if len(payload.Chunks) == 0 || len(payload.Chunks) > 1000 {
		writeError(w, http.StatusUnprocessableEntity, "chunks must contain between 1 and 1000 items")
		return
	}
	sequence, err := s.store.UpsertChunks(payload.Chunks)
	if err != nil {
		writeStoreError(w, err)
		return
	}
	ids := make([]string, len(payload.Chunks))
	for i, chunk := range payload.Chunks {
		ids[i] = chunk.ID
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"ids": ids, "sequence": sequence, "count": len(ids), "status": "committed",
	})
}

func (s *Server) deleteChunk(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	sequence, err := s.store.DeleteChunk(id)
	if err != nil {
		writeStoreError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"id": id, "sequence": sequence, "status": "deleted",
	})
}

func (s *Server) getChunk(w http.ResponseWriter, r *http.Request) {
	chunk, ok := s.store.GetChunk(r.PathValue("id"))
	if !ok {
		writeError(w, http.StatusNotFound, "chunk not found")
		return
	}
	writeJSON(w, http.StatusOK, chunk)
}

func (s *Server) search(w http.ResponseWriter, r *http.Request) {
	var options engine.SearchOptions
	if err := decodeJSON(w, r, &options); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	hits, err := s.store.Search(options)
	if err != nil {
		writeStoreError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"results": hits, "count": len(hits), "sequence": s.store.Sequence(),
	})
}

func (s *Server) putEvidence(w http.ResponseWriter, r *http.Request) {
	var item engine.Evidence
	if err := decodeJSON(w, r, &item); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	sequence, err := s.store.PutEvidence(item)
	if err != nil {
		writeStoreError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"id": item.ID, "sequence": sequence, "status": "committed",
	})
}

func (s *Server) getEvidence(w http.ResponseWriter, r *http.Request) {
	items := s.store.EvidenceForChunk(r.PathValue("id"))
	writeJSON(w, http.StatusOK, map[string]any{"results": items, "count": len(items)})
}

func decodeJSON(w http.ResponseWriter, r *http.Request, dst any) error {
	r.Body = http.MaxBytesReader(w, r.Body, maxRequestBytes)
	defer r.Body.Close()
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(dst); err != nil {
		return err
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("request must contain a single JSON value")
		}
		return err
	}
	return nil
}

func writeStoreError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, engine.ErrInvalidInput):
		writeError(w, http.StatusUnprocessableEntity, err.Error())
	case errors.Is(err, engine.ErrNotFound):
		writeError(w, http.StatusNotFound, err.Error())
	case errors.Is(err, engine.ErrClosed), errors.Is(err, engine.ErrPoisoned):
		writeError(w, http.StatusServiceUnavailable, "database is unavailable")
	case errors.Is(err, engine.ErrCorruptWAL):
		slog.Error("native database WAL is corrupt", "error", err)
		writeError(w, http.StatusInternalServerError, "database integrity error")
	default:
		slog.Error("native database request failed", "error", err)
		writeError(w, http.StatusInternalServerError, "database operation failed")
	}
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil {
		slog.Error("write JSON response failed", "error", err)
	}
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}

func requestLimits(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Cache-Control", "no-store")
		next.ServeHTTP(w, r)
	})
}

func constantTimeEqual(left, right string) bool {
	return subtle.ConstantTimeCompare([]byte(left), []byte(right)) == 1
}
