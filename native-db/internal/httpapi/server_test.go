package httpapi

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/premchandkpc/archMind/native-db/internal/engine"
)

func TestChunkSearchAPIRequiresTokenAndReturnsResults(t *testing.T) {
	store, err := engine.Open(filepath.Join(t.TempDir(), "data"))
	if err != nil { t.Fatal(err) }
	defer store.Close()

	handler := New(store, "test-token")
	body := `{"id":"c1","project_id":"p1","document_id":"d1","revision_id":"r1","content":"IS:456 concrete column","metadata":{"discipline":"structural"},"vector":[1,0]}`
	request := httptest.NewRequest(http.MethodPut, "/v1/chunks", bytes.NewBufferString(body))
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusUnauthorized { t.Fatalf("unauthenticated status = %d, want 401", response.Code) }

	request = httptest.NewRequest(http.MethodPut, "/v1/chunks", bytes.NewBufferString(body))
	request.Header.Set("Authorization", "Bearer test-token")
	response = httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusOK { t.Fatalf("put status = %d body=%s", response.Code, response.Body.String()) }

	query := `{"query":"IS:456","project_id":"p1","metadata_filter":{"discipline":"structural"},"query_vector":[1,0]}`
	request = httptest.NewRequest(http.MethodPost, "/v1/search", bytes.NewBufferString(query))
	request.Header.Set("Authorization", "Bearer test-token")
	response = httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusOK { t.Fatalf("search status = %d body=%s", response.Code, response.Body.String()) }

	var result map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil { t.Fatal(err) }
	if result["count"] != float64(1) { t.Fatalf("unexpected response: %#v", result) }
	results, ok := result["results"].([]any)
	if !ok || len(results) != 1 { t.Fatalf("unexpected results: %#v", result["results"]) }
	first, ok := results[0].(map[string]any)
	if !ok { t.Fatalf("unexpected first result: %#v", results[0]) }
	chunk, ok := first["chunk"].(map[string]any)
	if !ok || chunk["id"] != "c1" { t.Fatalf("unexpected chunk: %#v", first["chunk"]) }
}

func TestMissingTokenFailsClosed(t *testing.T) {
	store, err := engine.Open(t.TempDir())
	if err != nil { t.Fatal(err) }
	defer store.Close()
	handler := New(store, "")
	request := httptest.NewRequest(http.MethodGet, "/v1/stats", nil)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusServiceUnavailable { t.Fatalf("status = %d, want 503", response.Code) }
}

func TestRejectsUnknownJSONFields(t *testing.T) {
	store, err := engine.Open(t.TempDir())
	if err != nil { t.Fatal(err) }
	defer store.Close()
	handler := New(store, "secret")
	body := `{"id":"c1","project_id":"p1","document_id":"d1","revision_id":"r1","content":"hello","surprise":true}`
	request := httptest.NewRequest(http.MethodPut, "/v1/chunks", bytes.NewBufferString(body))
	request.Header.Set("Authorization", "Bearer secret")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusBadRequest { t.Fatalf("status = %d body=%s, want 400", response.Code, response.Body.String()) }
}
