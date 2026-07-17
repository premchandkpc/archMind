"""LangGraph workflow state — TypedDict flowing through every node.

LangGraph requires TypedDict for state, not Pydantic.
Annotated reducers merge state from parallel nodes.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class RetrievedChunk(TypedDict):
    """Single retrieved document chunk."""

    id: str
    content: str
    score: float
    source: str
    metadata: dict[str, Any]


class DrawingAnalysis(TypedDict):
    """Parsed architectural drawing data."""

    drawing_type: str  # floor_plan, structural, electrical, plumbing
    rooms: list[dict[str, Any]]
    walls: list[dict[str, Any]]
    doors: list[dict[str, Any]]
    windows: list[dict[str, Any]]
    columns: list[dict[str, Any]]
    beams: list[dict[str, Any]]
    dimensions: dict[str, Any]
    notes: list[str]


class Violation(TypedDict):
    """Building code violation."""

    rule: str
    section: str
    description: str
    severity: str  # critical, warning, info
    suggested_fix: str


class CostEstimate(TypedDict):
    """Cost estimation result."""

    items: list[dict[str, Any]]
    total: float
    currency: str
    confidence: float
    breakdown: dict[str, Any]
    summary: str


class Schedule(TypedDict):
    """Project schedule."""

    tasks: list[dict[str, Any]]
    duration_days: int
    critical_path: list[str]
    gantt_data: list[dict[str, Any]]


class RiskAssessment(TypedDict):
    """Risk analysis result."""

    risks: list[dict[str, Any]]
    overall_risk: str  # low, medium, high, critical
    mitigation: list[str]


class ReviewFeedback(TypedDict):
    """Reviewer node output."""

    is_valid: bool
    issues: list[str]
    missing_documents: list[str]
    calculation_errors: list[str]
    suggestions: list[str]


class ProjectState(TypedDict):
    """Main state flowing through LangGraph workflow.

    Every node reads from and writes to this state.
    Annotated fields use reducers to merge parallel node output.
    """

    # Input
    project_id: str
    question: str
    document_ids: list[str]

    # Retrieval
    retrieved_chunks: Annotated[list[RetrievedChunk], add_messages]

    # Analysis results
    drawing_analysis: DrawingAnalysis | None
    violations: Annotated[list[Violation], add_messages]
    cost_estimation: CostEstimate | None
    schedule: Schedule | None
    risk_assessment: RiskAssessment | None

    # Review
    review_feedback: ReviewFeedback | None

    # CrewAI hybrid analysis result
    analysis_result: str | None

    # Output
    final_answer: str | None

    # Workflow control
    messages: Annotated[list[dict[str, Any]], add_messages]
    iteration: int
    needs_human_approval: bool
    current_node: str
    next_nodes: list[str]

    # Memory
    context: dict[str, Any]


def create_initial_state(
    project_id: str,
    question: str,
    document_ids: list[str] | None = None,
) -> ProjectState:
    """Create fresh ProjectState with defaults.

    Args:
        project_id: Project identifier.
        question: User question.
        document_ids: Optional list of document IDs to consider.

    Returns:
        Initialized ProjectState.
    """
    return ProjectState(
        project_id=project_id,
        question=question,
        document_ids=document_ids or [],
        retrieved_chunks=[],
        drawing_analysis=None,
        violations=[],
        cost_estimation=None,
        schedule=None,
        risk_assessment=None,
        review_feedback=None,
        analysis_result=None,
        final_answer=None,
        messages=[],
        iteration=0,
        needs_human_approval=False,
        current_node="start",
        next_nodes=[],
        context={},
    )
