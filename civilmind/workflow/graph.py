"""LangGraph workflow graph — assembles nodes, edges, and routing.

Builds the StateGraph with conditional routing.
Planner decides which nodes to run.
Reviewer decides whether to loop back or proceed to report.
"""

from __future__ import annotations

from typing import Any

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from civilmind.config import MAX_ITERATIONS
from civilmind.workflow.nodes import (
    NODE_REGISTRY,
    analysis_crew_node,
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
)
from civilmind.workflow.state import ProjectState

logger = structlog.get_logger()

# Planner output → actual node names
NODE_MAP: dict[str, str] = {
    "retrieval": "retriever",
    "drawing_analysis": "drawing_analyzer",
    "compliance_check": "compliance",
    "estimation": "estimator",
    "scheduling": "scheduler",
    "risk_analysis": "risk_analyzer",
    "complex_analysis": "analysis_crew",
}


async def route_after_planner(state: ProjectState) -> str:
    """Route based on planner decision.

    Args:
        state: Current workflow state.

    Returns:
        Name of next node to execute.
    """
    next_nodes = state.get("next_nodes", ["retriever"])
    mapped = [NODE_MAP.get(n, n) for n in next_nodes]
    chosen = mapped[0] if mapped else "reviewer"
    logger.info("Routing after planner", next_nodes=mapped, chosen=chosen)
    return chosen


async def route_after_review(state: ProjectState) -> str:
    """Route based on review feedback.

    Args:
        state: Current workflow state.

    Returns:
        Either 'reporter' or 'planner' to loop back.
    """
    review = state.get("review_feedback") or {}
    iteration = state.get("iteration", 0)

    if review.get("is_valid", False):
        logger.info("Review passed, routing to reporter")
        return "reporter"
    if iteration < MAX_ITERATIONS:
        logger.info("Review failed, looping back to planner", iteration=iteration)
        return "planner"
    logger.info("Max iterations reached, routing to reporter", iteration=iteration)
    return "reporter"


def build_graph(checkpointer: Any | None = None) -> Any:
    """Build compiled LangGraph workflow.

    Args:
        checkpointer: Optional checkpointer for state persistence.
            Defaults to MemorySaver (in-memory).

    Returns:
        Compiled StateGraph ready for invoke/ainvoke/stream.
    """
    graph = StateGraph(ProjectState)

    # Nodes
    graph.add_node("planner", planner_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("drawing_analyzer", drawing_analyzer_node)
    graph.add_node("compliance", compliance_node)
    graph.add_node("estimator", estimator_node)
    graph.add_node("scheduler", scheduler_node)
    graph.add_node("risk_analyzer", risk_analyzer_node)
    graph.add_node("analysis_crew", analysis_crew_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("reporter", reporter_node)
    graph.add_node("human_approval", human_approval_node)

    # Entry
    graph.set_entry_point("planner")

    # Conditional edges from planner
    graph.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "retriever": "retriever",
            "drawing_analyzer": "drawing_analyzer",
            "compliance": "compliance",
            "estimator": "estimator",
            "scheduler": "scheduler",
            "risk_analyzer": "risk_analyzer",
            "analysis_crew": "analysis_crew",
            "reviewer": "reviewer",
        },
    )

    # All analysis nodes → reviewer
    graph.add_edge("retriever", "reviewer")
    graph.add_edge("drawing_analyzer", "reviewer")
    graph.add_edge("compliance", "reviewer")
    graph.add_edge("estimator", "reviewer")
    graph.add_edge("scheduler", "reviewer")
    graph.add_edge("risk_analyzer", "reviewer")
    graph.add_edge("analysis_crew", "reviewer")

    # Conditional edges from reviewer
    graph.add_conditional_edges(
        "reviewer",
        route_after_review,
        {
            "planner": "planner",
            "reporter": "reporter",
        },
    )

    # Terminal edges
    graph.add_edge("reporter", END)
    graph.add_edge("human_approval", END)

    compiled = graph.compile(checkpointer=checkpointer or MemorySaver())
    logger.info("Workflow graph built", nodes=list(NODE_REGISTRY.keys()))
    return compiled
