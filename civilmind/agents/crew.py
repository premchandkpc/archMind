"""Crew orchestration — assembles agents into a collaborative Crew.

CivilMindCrew manages the lifecycle of a multi-agent construction analysis.
Hierarchical process: Planner delegates to specialists.
"""

from __future__ import annotations

from typing import Any

import structlog
from crewai import Crew, Process, Task

from civilmind.agents.roles import AgentFactory

logger = structlog.get_logger()


class CivilMindCrew:
    """Orchestrates multiple AI agents for construction analysis.

    Creates agents, defines tasks, and executes the crew.
    """

    def __init__(
        self,
        project_id: str,
        question: str,
        documents: list[dict[str, str]] | None = None,
        tools: dict[str, Any] | None = None,
    ) -> None:
        """Initialize crew with project context.

        Args:
            project_id: Project identifier.
            question: User's construction question.
            documents: List of document metadata dicts.
            tools: Dict mapping tool names to CrewAI tool instances.
        """
        self.project_id = project_id
        self.question = question
        self.documents = documents or []
        self._tools = tools or {}

        self._factory = AgentFactory(tools=self._tools)
        self._agents = self._factory.create_all()
        self._tasks = self._create_tasks()

    def _create_tasks(self) -> list[Task]:
        """Create tasks for each agent.

        Returns:
            List of Task objects defining agent work.
        """
        doc_summary = "\n".join(f"- {d.get('filename', 'unknown')}" for d in self.documents[:10])

        tasks = [
            Task(
                description=(
                    f"Analyze this construction question and create a plan:\n\n"
                    f"Question: {self.question}\n"
                    f"Available documents:\n{doc_summary}\n\n"
                    f"Identify which specialists are needed and what each should do."
                ),
                agent=self._agents["planner"],
                expected_output="JSON with tasks and required specialists",
            ),
            Task(
                description=(
                    f"Search project documents for information relevant to:\n\n"
                    f"Question: {self.question}\n\n"
                    f"Find all related specs, codes, and reference materials."
                ),
                agent=self._agents["retriever"],
                expected_output="List of relevant document chunks with sources",
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
                    "Check for:\n"
                    "- Calculation errors\n"
                    "- Missing information\n"
                    "- Contradictions between analyses\n"
                    "- Code violations missed"
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

    def run(self) -> str:
        """Execute the crew and return the final report.

        Returns:
            Final report content from the report writer agent.
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

        logger.info(
            "Crew execution completed",
            project_id=self.project_id,
            result_length=len(str(result)),
        )

        return str(result)

    def get_agents(self) -> dict[str, Any]:
        """Get all agents.

        Returns:
            Dict mapping agent names to Agent instances.
        """
        return self._agents.copy()

    def get_tasks(self) -> list[Task]:
        """Get all tasks.

        Returns:
            List of Task objects.
        """
        return self._tasks.copy()
