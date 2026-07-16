"""Tests for workflow nodes — mocks LLM to avoid real API calls."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

from civilmind.llm.client import LLMClient
from civilmind.workflow.nodes import (
    compliance_node,
    drawing_analyzer_node,
    estimator_node,
    human_approval_node,
    planner_node,
    reporter_node,
    retriever_node,
    reviewer_node,
    risk_analyzer_node,
    scheduler_node,
    set_llm,
)
from civilmind.workflow.state import create_initial_state


@dataclass
class MockLLMResult:
    content: str
    model: str = "mock"
    tokens_used: int | None = None
    finish_reason: str | None = None


def _mock_llm(json_data: dict[str, Any]) -> LLMClient:
    """Create mock LLM client returning JSON."""
    client = AsyncMock(spec=LLMClient)
    client.chat = AsyncMock(return_value=MockLLMResult(content=json.dumps(json_data)))
    return client


class TestPlannerNode:
    def test_returns_next_nodes(self) -> None:
        plan = {"tasks": ["t1"], "required_nodes": ["retrieval"], "complexity": "low"}
        set_llm(_mock_llm(plan))
        state = create_initial_state("p1", "What is cost?")
        result = planner_node(state)

        # Run async
        import asyncio

        out = asyncio.get_event_loop().run_until_complete(result)

        assert "retrieval" in out["next_nodes"]
        assert out["current_node"] == "planner"
        assert len(out["messages"]) == 1

    def test_default_nodes_when_empty(self) -> None:
        set_llm(_mock_llm({"tasks": []}))
        state = create_initial_state("p1", "q")

        import asyncio

        out = asyncio.get_event_loop().run_until_complete(planner_node(state))

        assert out["next_nodes"] == ["retrieval"]


class TestRetrieverNode:
    def test_returns_empty_chunks(self) -> None:
        state = create_initial_state("p1", "q")

        import asyncio

        out = asyncio.get_event_loop().run_until_complete(retriever_node(state))

        assert out["retrieved_chunks"] == []
        assert out["current_node"] == "retriever"


class TestDrawingAnalyzerNode:
    def test_returns_none_analysis(self) -> None:
        state = create_initial_state("p1", "q")

        import asyncio

        out = asyncio.get_event_loop().run_until_complete(drawing_analyzer_node(state))

        assert out["drawing_analysis"] is None
        assert out["current_node"] == "drawing_analyzer"


class TestComplianceNode:
    def test_returns_violations(self) -> None:
        data = {
            "violations": [
                {
                    "rule": "IS 456",
                    "section": "5.3",
                    "description": "Min cover",
                    "severity": "critical",
                    "suggested_fix": "Increase",
                }
            ]
        }
        set_llm(_mock_llm(data))
        state = create_initial_state("p1", "Check compliance")

        import asyncio

        out = asyncio.get_event_loop().run_until_complete(compliance_node(state))

        assert len(out["violations"]) == 1
        assert out["violations"][0]["severity"] == "critical"


class TestEstimatorNode:
    def test_returns_cost_estimate(self) -> None:
        data = {
            "items": [{"item": "Concrete", "quantity": 45}],
            "total": 500000,
            "currency": "INR",
            "confidence": 0.75,
            "breakdown": {},
            "summary": "Total",
        }
        set_llm(_mock_llm(data))
        state = create_initial_state("p1", "Estimate cost")

        import asyncio

        out = asyncio.get_event_loop().run_until_complete(estimator_node(state))

        assert out["cost_estimation"]["total"] == 500000
        assert out["current_node"] == "estimator"


class TestSchedulerNode:
    def test_returns_schedule(self) -> None:
        data = {
            "tasks": [{"name": "Foundation", "duration_days": 15}],
            "duration_days": 90,
            "critical_path": ["Foundation"],
            "gantt_data": [],
        }
        set_llm(_mock_llm(data))
        state = create_initial_state("p1", "Create schedule")

        import asyncio

        out = asyncio.get_event_loop().run_until_complete(scheduler_node(state))

        assert out["schedule"]["duration_days"] == 90


class TestRiskAnalyzerNode:
    def test_returns_risk_assessment(self) -> None:
        data = {
            "risks": [{"name": "Price volatility"}],
            "overall_risk": "medium",
            "mitigation": ["Lock prices"],
        }
        set_llm(_mock_llm(data))
        state = create_initial_state("p1", "Analyze risks")

        import asyncio

        out = asyncio.get_event_loop().run_until_complete(risk_analyzer_node(state))

        assert out["risk_assessment"]["overall_risk"] == "medium"


class TestReviewerNode:
    def test_valid_when_chunks_exist(self) -> None:
        state = create_initial_state("p1", "q")
        state["retrieved_chunks"] = [
            {"id": "c1", "content": "text", "score": 0.9, "source": "doc", "metadata": {}}
        ]
        state["cost_estimation"] = {"confidence": 0.8}

        import asyncio

        out = asyncio.get_event_loop().run_until_complete(reviewer_node(state))

        assert out["review_feedback"]["is_valid"] is True
        assert out["next_nodes"] == ["reporter"]

    def test_invalid_when_no_chunks(self) -> None:
        state = create_initial_state("p1", "q")

        import asyncio

        out = asyncio.get_event_loop().run_until_complete(reviewer_node(state))

        assert out["review_feedback"]["is_valid"] is False
        assert "planner" in out["next_nodes"]
        assert out["iteration"] == 1

    def test_loops_back_on_critical_violations(self) -> None:
        state = create_initial_state("p1", "q")
        state["retrieved_chunks"] = [
            {"id": "c1", "content": "text", "score": 0.9, "source": "doc", "metadata": {}}
        ]
        state["violations"] = [
            {
                "rule": "R1",
                "section": "S1",
                "description": "d",
                "severity": "critical",
                "suggested_fix": "f",
            }
        ]

        import asyncio

        out = asyncio.get_event_loop().run_until_complete(reviewer_node(state))

        assert out["review_feedback"]["is_valid"] is False

    def test_max_iterations_force_report(self) -> None:
        state = create_initial_state("p1", "q")
        state["iteration"] = 3  # MAX_ITERATIONS

        import asyncio

        out = asyncio.get_event_loop().run_until_complete(reviewer_node(state))

        assert out["review_feedback"]["is_valid"] is True
        assert out["next_nodes"] == ["reporter"]


class TestReporterNode:
    def test_generates_report(self) -> None:
        set_llm(_mock_llm({}))  # reporter uses raw chat, not JSON
        # Override to return string
        client = AsyncMock(spec=LLMClient)
        client.chat = AsyncMock(return_value=MockLLMResult(content="# Report\nCost: 500k"))
        set_llm(client)

        state = create_initial_state("p1", "Generate report")

        import asyncio

        out = asyncio.get_event_loop().run_until_complete(reporter_node(state))

        assert "# Report" in out["final_answer"]
        assert out["current_node"] == "reporter"


class TestHumanApprovalNode:
    def test_flags_approval_needed(self) -> None:
        state = create_initial_state("p1", "q")

        import asyncio

        out = asyncio.get_event_loop().run_until_complete(human_approval_node(state))

        assert out["needs_human_approval"] is True
        assert out["current_node"] == "human_approval"
