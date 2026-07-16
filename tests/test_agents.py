"""Tests for agents — validates agent creation and crew assembly."""

from __future__ import annotations

from civilmind.agents.crew import CivilMindCrew
from civilmind.agents.roles import AgentFactory
from civilmind.agents.tools import (
    CalculatorTool,
    CodeSearchTool,
    OCRTool,
    SQLQueryTool,
    VectorSearchTool,
    VisionLLMTool,
    WeatherAPITool,
)


class TestAgentFactory:
    def test_create_all_agents(self) -> None:
        factory = AgentFactory()
        agents = factory.create_all()

        assert len(agents) == 9
        assert "planner" in agents
        assert "retriever" in agents
        assert "drawing_analyzer" in agents
        assert "compliance" in agents
        assert "estimator" in agents
        assert "scheduler" in agents
        assert "risk_analyzer" in agents
        assert "reviewer" in agents
        assert "report_writer" in agents

    def test_create_planner(self) -> None:
        factory = AgentFactory()
        agent = factory.create_planner()

        assert agent.role == "Project Planner"
        assert "construction" in agent.goal.lower()

    def test_create_retriever(self) -> None:
        factory = AgentFactory()
        agent = factory.create_retriever()

        assert agent.role == "Document Specialist"

    def test_create_drawing_analyzer(self) -> None:
        factory = AgentFactory()
        agent = factory.create_drawing_analyzer()

        assert agent.role == "Drawing Expert"

    def test_create_compliance(self) -> None:
        factory = AgentFactory()
        agent = factory.create_compliance()

        assert agent.role == "Code Officer"

    def test_create_estimator(self) -> None:
        factory = AgentFactory()
        agent = factory.create_estimator()

        assert agent.role == "Quantity Surveyor"

    def test_create_scheduler(self) -> None:
        factory = AgentFactory()
        agent = factory.create_scheduler()

        assert agent.role == "Planning Engineer"

    def test_create_risk_analyzer(self) -> None:
        factory = AgentFactory()
        agent = factory.create_risk_analyzer()

        assert agent.role == "Risk Analyst"

    def test_create_reviewer(self) -> None:
        factory = AgentFactory()
        agent = factory.create_reviewer()

        assert agent.role == "Quality Reviewer"

    def test_create_report_writer(self) -> None:
        factory = AgentFactory()
        agent = factory.create_report_writer()

        assert agent.role == "Technical Writer"

    def test_factory_with_tools(self) -> None:
        from civilmind.agents.tools import CalculatorTool, VectorSearchTool

        tools = {
            "vector_search": VectorSearchTool(),
            "calculator": CalculatorTool(),
        }
        factory = AgentFactory(tools=tools)
        agents = factory.create_all()

        assert len(agents) == 9


class TestCrewAIWrappers:
    def test_vector_search_tool_init(self) -> None:
        tool = VectorSearchTool()
        assert tool.name == "vector_search"

    def test_sql_query_tool_init(self) -> None:
        tool = SQLQueryTool()
        assert tool.name == "sql_query"

    def test_calculator_tool_init(self) -> None:
        tool = CalculatorTool()
        assert tool.name == "calculator"

    def test_ocr_tool_init(self) -> None:
        tool = OCRTool()
        assert tool.name == "ocr"

    def test_vision_llm_tool_init(self) -> None:
        tool = VisionLLMTool()
        assert tool.name == "vision_llm"

    def test_code_search_tool_init(self) -> None:
        tool = CodeSearchTool()
        assert tool.name == "code_search"

    def test_weather_api_tool_init(self) -> None:
        tool = WeatherAPITool()
        assert tool.name == "weather_api"

    def test_weather_api_stub(self) -> None:
        tool = WeatherAPITool()
        result = tool._run(location="Mumbai", date_range="next 7 days")
        assert "Mumbai" in result
        assert "next 7 days" in result

    def test_calculator_stub(self) -> None:
        tool = CalculatorTool()
        result = tool._run(expression="2 + 2")
        assert "stub" in result

    def test_vector_search_stub(self) -> None:
        tool = VectorSearchTool()
        result = tool._run(query="concrete specs")
        assert "stub" in result


class TestCivilMindCrew:
    def test_crew_creation(self) -> None:
        crew = CivilMindCrew(
            project_id="test-1",
            question="What is the cost of M25 concrete?",
        )

        assert crew.project_id == "test-1"
        assert "M25" in crew.question
        assert len(crew.get_agents()) == 9
        assert len(crew.get_tasks()) == 9

    def test_crew_with_documents(self) -> None:
        docs = [
            {"filename": "spec.pdf", "id": "doc1"},
            {"filename": "drawing.dwg", "id": "doc2"},
        ]
        crew = CivilMindCrew(
            project_id="test-2",
            question="Analyze this building",
            documents=docs,
        )

        assert len(crew.documents) == 2

    def test_crew_task_order(self) -> None:
        crew = CivilMindCrew(
            project_id="test-3",
            question="Schedule this project",
        )

        tasks = crew.get_tasks()
        # First task should be planner
        assert tasks[0].agent.role == "Project Planner"
        # Last task should be report writer
        assert tasks[-1].agent.role == "Technical Writer"
