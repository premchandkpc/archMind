"""Tests for workflow graph builder and routing."""

from __future__ import annotations

import asyncio

from civilmind.workflow.graph import build_graph, route_after_planner, route_after_review
from civilmind.workflow.state import create_initial_state


class TestRouteAfterPlanner:
    def test_maps_retrieval_to_retriever(self) -> None:
        state = create_initial_state("p1", "q")
        state["next_nodes"] = ["retrieval"]

        result = asyncio.get_event_loop().run_until_complete(route_after_planner(state))
        assert result == "retriever"

    def test_maps_estimation_to_estimator(self) -> None:
        state = create_initial_state("p1", "q")
        state["next_nodes"] = ["estimation"]

        result = asyncio.get_event_loop().run_until_complete(route_after_planner(state))
        assert result == "estimator"

    def test_passes_through_unknown(self) -> None:
        state = create_initial_state("p1", "q")
        state["next_nodes"] = ["custom_node"]

        result = asyncio.get_event_loop().run_until_complete(route_after_planner(state))
        assert result == "custom_node"

    def test_defaults_to_reviewer(self) -> None:
        state = create_initial_state("p1", "q")
        state["next_nodes"] = []

        result = asyncio.get_event_loop().run_until_complete(route_after_planner(state))
        assert result == "reviewer"

    def test_first_node_chosen(self) -> None:
        state = create_initial_state("p1", "q")
        state["next_nodes"] = ["retrieval", "estimation"]

        result = asyncio.get_event_loop().run_until_complete(route_after_planner(state))
        assert result == "retriever"

    def test_maps_complex_analysis_to_crew(self) -> None:
        state = create_initial_state("p1", "q")
        state["next_nodes"] = ["complex_analysis"]

        result = asyncio.get_event_loop().run_until_complete(route_after_planner(state))
        assert result == "analysis_crew"

    def test_maps_drawing_analysis_to_analyzer(self) -> None:
        state = create_initial_state("p1", "q")
        state["next_nodes"] = ["drawing_analysis"]

        result = asyncio.get_event_loop().run_until_complete(route_after_planner(state))
        assert result == "drawing_analyzer"

    def test_maps_compliance_check(self) -> None:
        state = create_initial_state("p1", "q")
        state["next_nodes"] = ["compliance_check"]

        result = asyncio.get_event_loop().run_until_complete(route_after_planner(state))
        assert result == "compliance"

    def test_maps_scheduling(self) -> None:
        state = create_initial_state("p1", "q")
        state["next_nodes"] = ["scheduling"]

        result = asyncio.get_event_loop().run_until_complete(route_after_planner(state))
        assert result == "scheduler"

    def test_maps_risk_analysis(self) -> None:
        state = create_initial_state("p1", "q")
        state["next_nodes"] = ["risk_analysis"]

        result = asyncio.get_event_loop().run_until_complete(route_after_planner(state))
        assert result == "risk_analyzer"


class TestRouteAfterReview:
    def test_valid_goes_to_reporter(self) -> None:
        state = create_initial_state("p1", "q")
        state["review_feedback"] = {"is_valid": True}

        result = asyncio.get_event_loop().run_until_complete(route_after_review(state))
        assert result == "reporter"

    def test_invalid_loops_to_planner(self) -> None:
        state = create_initial_state("p1", "q")
        state["review_feedback"] = {"is_valid": False}
        state["iteration"] = 1

        result = asyncio.get_event_loop().run_until_complete(route_after_review(state))
        assert result == "planner"

    def test_max_iterations_goes_to_reporter(self) -> None:
        state = create_initial_state("p1", "q")
        state["review_feedback"] = {"is_valid": False}
        state["iteration"] = 3

        result = asyncio.get_event_loop().run_until_complete(route_after_review(state))
        assert result == "reporter"

    def test_no_review_feedback_loops_to_planner(self) -> None:
        state = create_initial_state("p1", "q")

        result = asyncio.get_event_loop().run_until_complete(route_after_review(state))
        assert result == "planner"


class TestBuildGraph:
    def test_builds_without_error(self) -> None:
        graph = build_graph()
        assert graph is not None

    def test_has_expected_nodes(self) -> None:
        graph = build_graph()
        # Graph should be compiled and have nodes
        assert hasattr(graph, "get_graph")
