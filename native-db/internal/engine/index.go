package engine

import (
	"fmt"
	"math"
	"regexp"
	"sort"
	"strings"
)

var tokenPattern = regexp.MustCompile(`(?i)[a-z0-9]+(?:(?:[:._/-])[a-z0-9]+)*`)

type lexicalHit struct {
	id    string
	score float64
}

type searchIndex struct {
	chunks   map[string]Chunk
	postings map[string]map[string]int
	lengths  map[string]int
	terms    map[string]map[string]int
	avgLen   float64
}

func newSearchIndex() *searchIndex {
	return &searchIndex{
		chunks:   make(map[string]Chunk),
		postings: make(map[string]map[string]int),
		lengths:  make(map[string]int),
		terms:    make(map[string]map[string]int),
	}
}

// tokenize preserves engineering terms such as IS:456, M-20 and 5.3.
func tokenize(text string) []string {
	matches := tokenPattern.FindAllString(strings.ToLower(text), -1)
	return matches
}

func (idx *searchIndex) rebuild(chunks map[string]Chunk) {
	idx.chunks = make(map[string]Chunk, len(chunks))
	idx.postings = make(map[string]map[string]int)
	idx.lengths = make(map[string]int, len(chunks))
	idx.terms = make(map[string]map[string]int, len(chunks))
	total := 0
	for id, chunk := range chunks {
		idx.add(chunk)
		total += idx.lengths[id]
	}
	if len(idx.lengths) > 0 {
		idx.avgLen = float64(total) / float64(len(idx.lengths))
	} else {
		idx.avgLen = 0
	}
}

func (idx *searchIndex) upsert(chunk Chunk) {
	idx.delete(chunk.ID)
	idx.add(chunk)
	idx.recalculateAverage()
}

func (idx *searchIndex) add(chunk Chunk) {
	tokens := tokenize(chunk.Content)
	counts := make(map[string]int, len(tokens))
	for _, token := range tokens {
		counts[token]++
	}
	idx.chunks[chunk.ID] = cloneChunk(chunk)
	idx.terms[chunk.ID] = counts
	idx.lengths[chunk.ID] = len(tokens)
	for term, frequency := range counts {
		if idx.postings[term] == nil {
			idx.postings[term] = make(map[string]int)
		}
		idx.postings[term][chunk.ID] = frequency
	}
}

func (idx *searchIndex) delete(id string) {
	if _, exists := idx.chunks[id]; !exists {
		return
	}
	for term := range idx.terms[id] {
		delete(idx.postings[term], id)
		if len(idx.postings[term]) == 0 {
			delete(idx.postings, term)
		}
	}
	delete(idx.terms, id)
	delete(idx.lengths, id)
	delete(idx.chunks, id)
	idx.recalculateAverage()
}

func (idx *searchIndex) recalculateAverage() {
	total := 0
	for _, length := range idx.lengths {
		total += length
	}
	if len(idx.lengths) == 0 {
		idx.avgLen = 0
		return
	}
	idx.avgLen = float64(total) / float64(len(idx.lengths))
}

func (idx *searchIndex) lexicalSearch(query string, allowed map[string]struct{}, limit int) []lexicalHit {
	queryTerms := tokenize(query)
	if len(queryTerms) == 0 || len(allowed) == 0 {
		return nil
	}
	scores := make(map[string]float64)
	totalDocs := float64(len(allowed))
	const k1, b = 1.5, 0.75
	for _, term := range queryTerms {
		posting := idx.postings[term]
		if len(posting) == 0 {
			continue
		}
		df := 0
		for id := range posting {
			if _, ok := allowed[id]; ok {
				df++
			}
		}
		if df == 0 {
			continue
		}
		idf := math.Log(1 + (totalDocs-float64(df)+0.5)/(float64(df)+0.5))
		for id, frequency := range posting {
			if _, ok := allowed[id]; !ok {
				continue
			}
			length := float64(idx.lengths[id])
			avgLen := math.Max(idx.avgLen, 1)
			norm := k1 * (1 - b + b*length/avgLen)
			tf := float64(frequency)
			scores[id] += idf * tf * (k1 + 1) / (tf + norm)
		}
	}
	hits := make([]lexicalHit, 0, len(scores))
	for id, score := range scores {
		if score > 0 {
			hits = append(hits, lexicalHit{id: id, score: score})
		}
	}
	sort.Slice(hits, func(i, j int) bool {
		if hits[i].score == hits[j].score {
			return hits[i].id < hits[j].id
		}
		return hits[i].score > hits[j].score
	})
	if len(hits) > limit {
		hits = hits[:limit]
	}
	return hits
}

func (idx *searchIndex) vectorSearch(query []float64, allowed map[string]struct{}, limit int) ([]lexicalHit, error) {
	if len(query) == 0 {
		return nil, fmt.Errorf("%w: empty query vector", ErrInvalidInput)
	}
	queryNorm := vectorNorm(query)
	if queryNorm == 0 || math.IsInf(queryNorm, 0) || math.IsNaN(queryNorm) {
		return nil, fmt.Errorf("%w: query vector is zero", ErrInvalidInput)
	}
	hits := make([]lexicalHit, 0)
	for id := range allowed {
		chunk, exists := idx.chunks[id]
		if !exists || len(chunk.Vector) == 0 {
			continue
		}
		if len(chunk.Vector) != len(query) {
			return nil, fmt.Errorf("%w: query vector dimension %d differs from stored dimension %d", ErrInvalidInput, len(query), len(chunk.Vector))
		}
		norm := vectorNorm(chunk.Vector)
		if norm == 0 || math.IsInf(norm, 0) || math.IsNaN(norm) {
			continue
		}
		cosine := 0.0
		for i := range query {
			cosine += (query[i] / queryNorm) * (chunk.Vector[i] / norm)
		}
		hits = append(hits, lexicalHit{id: id, score: cosine})
	}
	sort.Slice(hits, func(i, j int) bool {
		if hits[i].score == hits[j].score {
			return hits[i].id < hits[j].id
		}
		return hits[i].score > hits[j].score
	})
	if len(hits) > limit {
		hits = hits[:limit]
	}
	return hits, nil
}
