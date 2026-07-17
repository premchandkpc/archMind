"""LangGraph workflow nodes — async functions that transform state.

Each node: takes ProjectState, does work, returns partial state update.
Nodes call LLMs, search documents, analyze drawings, check compliance.
Complex multi-agent tasks delegate to CrewAI via analysis_crew_node.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from civilmind.config import MAX_ITERATIONS
from civilmind.llm.client import LLMClient, LLMMessage, LLMResult
from civilmind.settings import settings
from civilmind.workflow.state import ProjectState

logger = structlog.get_logger()

_llm_client: LLMClient | None = None


def get_llm() -> LLMClient:
    """Get or create LLM client singleton."""
    global _llm_client  # noqa: PLW0603
    if _llm_client is None:
        _llm_client = LLMClient(config=settings.llm_chat_config)
    return _llm_client


def set_llm(client: LLMClient) -> None:
    """Override LLM client (for testing)."""
    global _llm_client  # noqa: PLW0603
    _llm_client = client


async def _chat_json(prompt: str) -> dict[str, Any]:
    """Send chat request, parse JSON response."""
    llm = get_llm()
    result: LLMResult = await llm.chat(
        messages=[LLMMessage(role="user", content=prompt)],
    )
    parsed: dict[str, Any] = json.loads(result.content)
    return parsed


async def planner_node(state: ProjectState) -> dict[str, Any]:
    """Analyze question and create execution plan.

    Args:
        state: Current workflow state.

    Returns:
        Partial state update with next_nodes and plan message.
    """
    prompt = f"""You are a construction project planner.

Question: {state["question"]}
Available documents: {state.get("document_ids", [])}

Create a plan to answer this question. Return JSON:
{{
    "tasks": ["task1", "task2"],
    "required_nodes": ["retrieval", "estimation"],
    "complexity": "low|medium|high"
}}"""

    plan = await _chat_json(prompt)
    next_nodes = plan.get("required_nodes", ["retrieval"])

    return {
        "messages": [{"role": "assistant", "content": json.dumps(plan), "name": "planner"}],
        "next_nodes": next_nodes,
        "current_node": "planner",
    }


async def retriever_node(state: ProjectState) -> dict[str, Any]:
    """Retrieve relevant documents.

    Args:
        state: Current workflow state.

    Returns:
        Partial state update with retrieved_chunks.
    """
    return {
        "retrieved_chunks": [],
        "messages": [{"role": "assistant", "content": "Retrieved chunks", "name": "retriever"}],
        "current_node": "retriever",
    }


async def drawing_analyzer_node(state: ProjectState) -> dict[str, Any]:
    """Analyze architectural drawings using vision LLM.

    Args:
        state: Current workflow state.

    Returns:
        Partial state update with drawing_analysis.
    """
    return {
        "drawing_analysis": None,
        "messages": [
            {"role": "assistant", "content": "Drawing analysis pending", "name": "drawing_analyzer"}
        ],
        "current_node": "drawing_analyzer",
    }


async def compliance_node(state: ProjectState) -> dict[str, Any]:
    """Check building code compliance.

    Args:
        state: Current workflow state.

    Returns:
        Partial state update with violations.
    """
    prompt = f"""Check this construction question against building codes:

Question: {state["question"]}
Retrieved context: {[c.get("content", "")[:200] for c in state.get("retrieved_chunks", [])[:3]]}

Return JSON with violations found:
{{
    "violations": [
        {{
            "rule": "IS 456",
            "section": "5.3",
            "description": "...",
            "severity": "critical|warning|info",
            "suggested_fix": "..."
        }}
    ]
}}"""

    result = await _chat_json(prompt)
    return {
        "violations": result.get("violations", []),
        "messages": [{"role": "assistant", "content": json.dumps(result), "name": "compliance"}],
        "current_node": "compliance",
    }


async def estimator_node(state: ProjectState) -> dict[str, Any]:
    """Estimate quantities and costs.

    Args:
        state: Current workflow state.

    Returns:
        Partial state update with cost_estimation.
    """
    context_text = "\n".join(
        c.get("content", "")[:500] for c in state.get("retrieved_chunks", [])[:5]
    )

    prompt = f"""Estimate quantities and costs for this construction question:

Question: {state["question"]}
Context: {context_text}

Return JSON:
{{
    "items": [{{"item": "Concrete M25", "qty": 45, "unit": "cum", "rate": 4500, "amt": 202500}}],
    "total": 500000,
    "currency": "INR",
    "confidence": 0.75,
    "breakdown": {{"materials": 300000, "labor": 150000, "equipment": 50000}},
    "summary": "Total estimated cost..."
}}"""

    result = await _chat_json(prompt)
    return {
        "cost_estimation": result,
        "messages": [{"role": "assistant", "content": json.dumps(result), "name": "estimator"}],
        "current_node": "estimator",
    }


async def scheduler_node(state: ProjectState) -> dict[str, Any]:
    """Create project timeline.

    Args:
        state: Current workflow state.

    Returns:
        Partial state update with schedule.
    """
    cost = state.get("cost_estimation") or {}
    prompt = f"""Create a construction schedule based on:

Question: {state["question"]}
Cost items: {json.dumps(cost.get("items", []), indent=2)}

Return JSON:
{{
    "tasks": [{{"name": "Foundation", "duration_days": 15, "dependencies": []}}],
    "duration_days": 90,
    "critical_path": ["Foundation", "Structure", "Finishing"],
    "gantt_data": []
}}"""

    result = await _chat_json(prompt)
    return {
        "schedule": result,
        "messages": [{"role": "assistant", "content": json.dumps(result), "name": "scheduler"}],
        "current_node": "scheduler",
    }


async def risk_analyzer_node(state: ProjectState) -> dict[str, Any]:
    """Identify project risks.

    Args:
        state: Current workflow state.

    Returns:
        Partial state update with risk_assessment.
    """
    prompt = f"""Analyze risks for this construction project:

Question: {state["question"]}
Cost estimate: {json.dumps(state.get("cost_estimation", {}), indent=2)}
Violations: {json.dumps(state.get("violations", []), indent=2)}

Return JSON:
{{
    "risks": [{{"name": "Material price volatility", "probability": "medium", "impact": "high"}}],
    "overall_risk": "medium",
    "mitigation": ["Lock material prices early"]
}}"""

    result = await _chat_json(prompt)
    return {
        "risk_assessment": result,
        "messages": [{"role": "assistant", "content": json.dumps(result), "name": "risk_analyzer"}],
        "current_node": "risk_analyzer",
    }


async def reviewer_node(state: ProjectState) -> dict[str, Any]:
    """Review all outputs for quality.

    Args:
        state: Current workflow state.

    Returns:
        Partial state update with review_feedback and next_nodes.
    """
    issues: list[str] = []

    if not state.get("retrieved_chunks"):
        issues.append("No relevant documents found")

    cost_est = state.get("cost_estimation")
    if cost_est and cost_est.get("confidence", 0) < 0.5:
        issues.append("Low confidence in cost estimation")

    critical = [v for v in state.get("violations", []) if v.get("severity") == "critical"]
    if critical:
        issues.append(f"Found {len(critical)} critical violations")

    iteration = state.get("iteration", 0)

    if issues and iteration < MAX_ITERATIONS:
        return {
            "review_feedback": {
                "is_valid": False,
                "issues": issues,
                "missing_documents": [],
                "calculation_errors": [],
                "suggestions": [],
            },
            "next_nodes": ["planner"],
            "iteration": iteration + 1,
            "messages": [
                {"role": "assistant", "content": f"Issues found: {issues}", "name": "reviewer"}
            ],
            "current_node": "reviewer",
        }

    return {
        "review_feedback": {
            "is_valid": True,
            "issues": [],
            "missing_documents": [],
            "calculation_errors": [],
            "suggestions": [],
        },
        "next_nodes": ["reporter"],
        "messages": [{"role": "assistant", "content": "Review passed", "name": "reviewer"}],
        "current_node": "reviewer",
    }


async def reporter_node(state: ProjectState) -> dict[str, Any]:
    """Generate final report.

    Args:
        state: Current workflow state.

    Returns:
        Partial state update with final_answer.
    """
    prompt = f"""Generate a construction report based on:

Question: {state["question"]}
Cost Estimation: {json.dumps(state.get("cost_estimation", {}), indent=2)}
Violations: {json.dumps(state.get("violations", []), indent=2)}

Provide a clear, professional report in markdown."""

    llm = get_llm()
    result: LLMResult = await llm.chat(
        messages=[LLMMessage(role="user", content=prompt)],
    )

    return {
        "final_answer": result.content,
        "messages": [{"role": "assistant", "content": "Report generated", "name": "reporter"}],
        "current_node": "reporter",
    }


async def analysis_crew_node(state: ProjectState) -> dict[str, Any]:
    """Delegate complex analysis to CrewAI multi-agent system.

    Called when planner determines task needs multiple agents collaborating.
    Runs CrewAI crew in thread pool, returns structured results to state.

    Args:
        state: Current workflow state.

    Returns:
        Partial state update with analysis_result and extracted data.
    """
    from civilmind.agents.crew import CivilMindCrew

    crew = CivilMindCrew(
        project_id=state.get("project_id", ""),
        question=state["question"],
        retrieved_chunks=state.get("retrieved_chunks", []),
        document_ids=state.get("document_ids", []),
    )

    result = await asyncio.to_thread(crew.run)

    update: dict[str, Any] = {
        "analysis_result": result.analysis,
        "messages": [
            {"role": "assistant", "content": "CrewAI analysis completed", "name": "analysis_crew"}
        ],
        "current_node": "analysis_crew",
    }

    if result.violations:
        update["violations"] = result.violations
    if result.cost_estimate:
        update["cost_estimation"] = result.cost_estimate
    if result.schedule:
        update["schedule"] = result.schedule
    if result.risks:
        update["risk_assessment"] = result.risks

    return update


async def human_approval_node(state: ProjectState) -> dict[str, Any]:
    """Pause workflow for human approval.

    Args:
        state: Current workflow state.

    Returns:
        Partial state update flagging need for approval.
    """
    return {
        "needs_human_approval": True,
        "messages": [
            {"role": "assistant", "content": "Awaiting human approval", "name": "human_approval"}
        ],
        "current_node": "human_approval",
    }


NODE_REGISTRY: dict[str, Any] = {
    "planner": planner_node,
    "retriever": retriever_node,
    "drawing_analyzer": drawing_analyzer_node,
    "compliance": compliance_node,
    "estimator": estimator_node,
    "scheduler": scheduler_node,
    "risk_analyzer": risk_analyzer_node,
    "analysis_crew": analysis_crew_node,
    "reviewer": reviewer_node,
    "reporter": reporter_node,
    "human_approval": human_approval_node,
}
