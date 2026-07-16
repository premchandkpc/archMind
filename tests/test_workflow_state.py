"""Tests for workflow state model."""

from __future__ import annotations

from civilmind.workflow.state import (
    CostEstimate,
    RetrievedChunk,
    ReviewFeedback,
    Violation,
    create_initial_state,
)


class TestCreateInitialState:
    """Tests for create_initial_state factory."""

    def test_basic_creation(self) -> None:
        state = create_initial_state(project_id="p1", question="What is the cost?")
        assert state["project_id"] == "p1"
        assert state["question"] == "What is the cost?"
        assert state["document_ids"] == []

    def test_with_document_ids(self) -> None:
        docs = ["doc1", "doc2", "doc3"]
        state = create_initial_state(project_id="p1", question="q", document_ids=docs)
        assert state["document_ids"] == docs

    def test_defaults_are_empty(self) -> None:
        state = create_initial_state(project_id="p1", question="q")
        assert state["retrieved_chunks"] == []
        assert state["drawing_analysis"] is None
        assert state["violations"] == []
        assert state["cost_estimation"] is None
        assert state["schedule"] is None
        assert state["risk_assessment"] is None
        assert state["review_feedback"] is None
        assert state["final_answer"] is None
        assert state["messages"] == []
        assert state["iteration"] == 0
        assert state["needs_human_approval"] is False
        assert state["current_node"] == "start"
        assert state["next_nodes"] == []
        assert state["context"] == {}


class TestTypedDicts:
    """Tests for helper TypedDicts."""

    def test_retrieved_chunk(self) -> None:
        chunk: RetrievedChunk = {
            "id": "c1",
            "content": "text",
            "score": 0.95,
            "source": "doc.pdf",
            "metadata": {"page": 1},
        }
        assert chunk["score"] == 0.95

    def test_violation(self) -> None:
        v: Violation = {
            "rule": "IS 456",
            "section": "5.3",
            "description": "Min cover",
            "severity": "critical",
            "suggested_fix": "Increase cover",
        }
        assert v["severity"] == "critical"

    def test_cost_estimate(self) -> None:
        c: CostEstimate = {
            "items": [],
            "total": 500000.0,
            "currency": "INR",
            "confidence": 0.75,
            "breakdown": {},
            "summary": "Total",
        }
        assert c["total"] == 500000.0

    def test_review_feedback(self) -> None:
        r: ReviewFeedback = {
            "is_valid": True,
            "issues": [],
            "missing_documents": [],
            "calculation_errors": [],
            "suggestions": [],
        }
        assert r["is_valid"] is True
