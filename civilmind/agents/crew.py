"""Crew orchestration — CrewAI agents called from LangGraph nodes.

CivilMindCrew accepts LangGraph state, runs multi-agent analysis,
and returns structured results back to the state machine.
"""

from __future__ import annotations

from typing import Any

import structlog
from crewai import Crew, Process, Task

from civilmind.agents.roles import AgentFactory

logger = structlog.get_logger()


class CrewResult:
    """Structured result from CrewAI execution back to LangGraph."""

    def __init__(
        self,
        analysis: str,
        chunks: list[dict[str, Any]] | None = None,
        violations: list[dict[str, Any]] | None = None,
        cost_estimate: dict[str, Any] | None = None,
        schedule: dict[str, Any] | None = None,
        risks: dict[str, Any] | None = None,
    ) -> None:
        self.analysis = analysis
        self.chunks = chunks or []
        self.violations = violations or []
        self.cost_estimate = cost_estimate
        self.schedule = schedule
        self.risks = risks

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis": self.analysis,
            "chunks": self.chunks,
            "violations": self.violations,
            "cost_estimate": self.cost_estimate,
            "schedule": self.schedule,
            "risks": self.risks,
        }


class CivilMindCrew:
    """Orchestrates CrewAI agents for complex multi-agent analysis.

    Called from LangGraph analysis_crew_node when a task needs
    multiple agents collaborating (retriever + drawing + compliance + estimator).
    """

    def __init__(
        self,
        project_id: str,
        question: str,
        retrieved_chunks: list[dict[str, Any]] | None = None,
        document_ids: list[str] | None = None,
        tools: dict[str, Any] | None = None,
    ) -> None:
        self.project_id = project_id
        self.question = question
        self.retrieved_chunks = retrieved_chunks or []
        self.document_ids = document_ids or []
        self._tools = tools or {}

        self._factory = AgentFactory(tools=self._tools)
        self._agents = self._factory.create_all()
        self._tasks = self._create_tasks()

    def _create_tasks(self) -> list[Task]:
        """Create tasks with LangGraph state context injected."""
        context_chunks = "\n".join(
            f"- {c.get('content', '')[:200]}" for c in self.retrieved_chunks[:5]
        )

        tasks = [
            Task(
                description=(
                    f"Search project documents for information relevant to:\n\n"
                    f"Question: {self.question}\n"
                    f"Already retrieved context:\n{context_chunks}\n\n"
                    f"Find any additional relevant information."
                ),
                agent=self._agents["retriever"],
                expected_output="Additional relevant document chunks",
            ),
            Task(
                description=(
                    f"Analyze any architectural drawings related to:\n\n"
                    f"Question: {self.question}\n\n"
                    f"Extract structural elements, dimensions, and key information."
                ),
                agent=self._agents["drawing_analyzer"],
                expected_output="Drawing analysis with extracted elements",
            ),
            Task(
                description=(
                    f"Check building code compliance for:\n\n"
                    f"Question: {self.question}\n\n"
                    f"Identify any violations of NBC 2016, IS456, IS875, or local codes."
                ),
                agent=self._agents["compliance"],
                expected_output="Compliance report with violations and severity",
            ),
            Task(
                description=(
                    f"Estimate quantities and costs for:\n\n"
                    f"Question: {self.question}\n\n"
                    f"Provide detailed BOQ with rates and totals in INR."
                ),
                agent=self._agents["estimator"],
                expected_output="Cost estimation with itemized BOQ",
            ),
            Task(
                description=(
                    f"Create construction schedule for:\n\n"
                    f"Question: {self.question}\n\n"
                    f"Identify tasks, durations, dependencies, and critical path."
                ),
                agent=self._agents["scheduler"],
                expected_output="Project schedule with Gantt data",
            ),
            Task(
                description=(
                    f"Analyze risks for:\n\n"
                    f"Question: {self.question}\n\n"
                    f"Identify technical, financial, and schedule risks with mitigations."
                ),
                agent=self._agents["risk_analyzer"],
                expected_output="Risk assessment matrix",
            ),
            Task(
                description=(
                    "Review all analysis outputs for quality and accuracy.\n\n"
                    "Check for calculation errors, missing information, "
                    "contradictions, and missed code violations."
                ),
                agent=self._agents["reviewer"],
                expected_output="Quality review with pass/fail and issues",
            ),
            Task(
                description=(
                    f"Generate a comprehensive construction report for:\n\n"
                    f"Question: {self.question}\n\n"
                    f"Include: analysis summary, cost estimate, schedule, risks, "
                    f"compliance status, and recommendations."
                ),
                agent=self._agents["report_writer"],
                expected_output="Professional construction report in markdown",
            ),
        ]

        logger.info(
            "Created crew tasks",
            project_id=self.project_id,
            task_count=len(tasks),
        )
        return tasks

    def run(self) -> CrewResult:
        """Execute crew and return structured result for LangGraph.

        Returns:
            CrewResult with analysis text and structured data.
        """
        crew = Crew(
            agents=list(self._agents.values()),
            tasks=self._tasks,
            process=Process.hierarchical,
            memory=True,
            verbose=True,
        )

        logger.info(
            "Starting crew execution",
            project_id=self.project_id,
            question=self.question[:100],
        )

        result = crew.kickoff()
        result_str = str(result)

        logger.info(
            "Crew execution completed",
            project_id=self.project_id,
            result_length=len(result_str),
        )

        return CrewResult(analysis=result_str)

    def get_agents(self) -> dict[str, Any]:
        return self._agents.copy()

    def get_tasks(self) -> list[Task]:
        return self._tasks.copy()
