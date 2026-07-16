"""Agent definitions — 9 specialized AI agents for construction analysis.

Each agent has a role, goal, backstory, and set of tools.
AgentFactory creates agents with tool injection for testability.
"""

from __future__ import annotations

from typing import Any

import structlog
from crewai import LLM, Agent

from civilmind.settings import settings

logger = structlog.get_logger()


class AgentFactory:
    """Creates specialized construction analysis agents.

    Agents are created with tools injected at runtime.
    Use create_*() methods or create_all() to build full team.
    """

    def __init__(self, tools: dict[str, Any] | None = None) -> None:
        """Initialize factory with available tools.

        Args:
            tools: Dict mapping tool names to CrewAI tool instances.
        """
        self._tools = tools or {}
        self._llm = LLM(
            model=f"openai/{settings.LLM_CHAT_MODEL}",
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
        )

    def create_planner(self) -> Agent:
        """Create project planner agent.

        Senior construction project manager with 20 years experience.
        Breaks down questions into tasks for specialist agents.
        """
        return Agent(
            role="Project Planner",
            goal=(
                "Break down construction questions into actionable tasks "
                "and delegate to specialists"
            ),
            backstory=(
                "Senior construction project manager with 20 years experience "
                "planning residential and commercial projects. Expert at understanding "
                "client requirements and translating them into technical tasks."
            ),
            tools=[self._tools.get("vector_search")].__class__(
                [t for t in [self._tools.get("vector_search")] if t]
            )
            if self._tools.get("vector_search")
            else [],
            llm=self._llm,
            verbose=True,
            allow_delegation=True,
        )

    def create_retriever(self) -> Agent:
        """Create document retrieval specialist.

        Expert at finding information in construction documents.
        """
        return Agent(
            role="Document Specialist",
            goal="Find relevant documents and information to answer construction questions",
            backstory=(
                "Expert at finding information in construction documents. Knows where to look "
                "for structural specs, building codes, material properties. Can navigate large "
                "document repositories efficiently."
            ),
            tools=[
                t
                for t in [
                    self._tools.get("vector_search"),
                    self._tools.get("sql_query"),
                ]
                if t
            ],
            llm=self._llm,
            verbose=True,
            allow_delegation=False,
        )

    def create_drawing_analyzer(self) -> Agent:
        """Create drawing analysis specialist.

        Civil engineer specializing in architectural and structural drawings.
        """
        return Agent(
            role="Drawing Expert",
            goal="Extract structural elements and information from architectural drawings",
            backstory=(
                "Civil engineer specializing in reading architectural and structural drawings. "
                "Can identify walls, columns, beams, doors, windows, and their dimensions. "
                "Expert at interpreting floor plans, elevations, and sections."
            ),
            tools=[
                t
                for t in [
                    self._tools.get("vision_llm"),
                    self._tools.get("ocr"),
                ]
                if t
            ],
            llm=self._llm,
            verbose=True,
            allow_delegation=False,
        )

    def create_compliance(self) -> Agent:
        """Create building code compliance specialist.

        Government building inspector with deep knowledge of Indian codes.
        """
        return Agent(
            role="Code Officer",
            goal="Check construction projects against building codes and regulations",
            backstory=(
                "Government building inspector with deep knowledge of Indian building codes. "
                "Knows every clause of NBC 2016, IS456, IS875. Can identify violations "
                "and suggest compliant alternatives."
            ),
            tools=[t for t in [self._tools.get("code_search")] if t],
            llm=self._llm,
            verbose=True,
            allow_delegation=False,
        )

    def create_estimator(self) -> Agent:
        """Create quantity surveyor agent.

        Certified quantity surveyor with Indian construction cost expertise.
        """
        return Agent(
            role="Quantity Surveyor",
            goal="Calculate quantities and costs for construction projects",
            backstory=(
                "Certified quantity surveyor with expertise in Indian construction costs. "
                "Can estimate concrete, steel, bricks, labor, and equipment costs. "
                "Expert at BOQ preparation and cost optimization."
            ),
            tools=[
                t
                for t in [
                    self._tools.get("calculator"),
                    self._tools.get("sql_query"),
                ]
                if t
            ],
            llm=self._llm,
            verbose=True,
            allow_delegation=False,
        )

    def create_scheduler(self) -> Agent:
        """Create planning engineer agent.

        Expert at creating construction schedules and identifying critical paths.
        """
        return Agent(
            role="Planning Engineer",
            goal="Create construction timelines and identify critical path activities",
            backstory=(
                "Planning engineer who has created schedules for hundreds of construction "
                "projects. Understands dependencies, critical paths, and resource leveling. "
                "Expert at Gantt charts and milestone tracking."
            ),
            tools=[t for t in [self._tools.get("calculator")] if t],
            llm=self._llm,
            verbose=True,
            allow_delegation=False,
        )

    def create_risk_analyzer(self) -> Agent:
        """Create risk analyst agent.

        Risk management professional specializing in construction.
        """
        return Agent(
            role="Risk Analyst",
            goal="Identify and assess risks in construction projects",
            backstory=(
                "Risk management professional specializing in construction. Knows common "
                "pitfalls, cost overrun patterns, and delay causes. Expert at creating "
                "risk matrices and mitigation strategies."
            ),
            tools=[t for t in [self._tools.get("weather_api")] if t],
            llm=self._llm,
            verbose=True,
            allow_delegation=False,
        )

    def create_reviewer(self) -> Agent:
        """Create quality reviewer agent.

        Senior engineer who validates all deliverables.
        """
        return Agent(
            role="Quality Reviewer",
            goal="Validate all outputs for accuracy, completeness, and quality",
            backstory=(
                "Senior engineer who reviews all deliverables. Catches calculation errors, "
                "missing information, and hallucinations. Ensures reports meet professional "
                "standards and client requirements."
            ),
            tools=[t for t in [self._tools.get("calculator")] if t],
            llm=self._llm,
            verbose=True,
            allow_delegation=False,
        )

    def create_report_writer(self) -> Agent:
        """Create technical writer agent.

        Expert at creating professional construction reports.
        """
        return Agent(
            role="Technical Writer",
            goal="Generate clear, professional construction reports",
            backstory=(
                "Technical writer who creates construction reports for architects, engineers, "
                "and government departments. Expert at translating technical data into "
                "readable, actionable reports."
            ),
            tools=[],
            llm=self._llm,
            verbose=True,
            allow_delegation=False,
        )

    def create_all(self) -> dict[str, Agent]:
        """Create all 9 agents.

        Returns:
            Dict mapping agent names to Agent instances.
        """
        agents = {
            "planner": self.create_planner(),
            "retriever": self.create_retriever(),
            "drawing_analyzer": self.create_drawing_analyzer(),
            "compliance": self.create_compliance(),
            "estimator": self.create_estimator(),
            "scheduler": self.create_scheduler(),
            "risk_analyzer": self.create_risk_analyzer(),
            "reviewer": self.create_reviewer(),
            "report_writer": self.create_report_writer(),
        }

        logger.info(
            "Created all agents",
            agents=list(agents.keys()),
            tools_per_agent={k: len(v.tools) for k, v in agents.items()},
        )

        return agents
