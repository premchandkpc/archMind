"""CrewAI tool wrappers — bridge project tools to CrewAI interface.

CrewAI expects _run() → str. Our tools use execute() → ToolResult.
These wrappers adapt the interface so agents can use existing tools.
"""

from __future__ import annotations

from typing import Any

import structlog
from crewai.tools import BaseTool as CrewBaseTool

from civilmind.tools.base import ToolResult

logger = structlog.get_logger()


class VectorSearchTool(CrewBaseTool):
    """Search project documents using semantic similarity."""

    name: str = "vector_search"
    description: str = "Search project documents using semantic similarity"

    _project_tool: Any = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, project_tool: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._project_tool = project_tool

    def _run(self, query: str, project_id: str = "default", top_k: int = 10) -> str:
        """Execute vector search (synchronous wrapper for CrewAI)."""
        import asyncio

        if self._project_tool is None:
            return f"Search results for '{query}' (stub — no tool connected)"

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result: ToolResult = pool.submit(
                        asyncio.run,
                        self._project_tool.execute(
                            query_vector=[], project_id=project_id, top_k=top_k
                        ),
                    ).result()
            else:
                result = loop.run_until_complete(
                    self._project_tool.execute(query_vector=[], project_id=project_id, top_k=top_k)
                )

            if result.success:
                chunks = result.data or []
                return f"Found {len(chunks)} relevant chunks:\n" + "\n".join(
                    f"- {c.get('content', '')[:200]}" for c in chunks[:5]
                )
            return f"Search failed: {result.error}"

        except Exception as e:
            logger.error("VectorSearch tool failed", error=str(e))
            return f"Search error: {e}"


class SQLQueryTool(CrewBaseTool):
    """Query the project database with read-only SQL."""

    name: str = "sql_query"
    description: str = "Query the project database for structured data"

    _project_tool: Any = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, project_tool: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._project_tool = project_tool

    def _run(self, query: str) -> str:
        """Execute SQL query (synchronous wrapper for CrewAI)."""
        if self._project_tool is None:
            return f"Query result for: {query} (stub)"

        import asyncio

        try:
            result: ToolResult = asyncio.run(self._project_tool.execute(query=query))
            if result.success:
                return str(result.data)
            return f"Query failed: {result.error}"
        except Exception as e:
            return f"Query error: {e}"


class CalculatorTool(CrewBaseTool):
    """Perform mathematical calculations safely."""

    name: str = "calculator"
    description: str = "Perform mathematical calculations"

    _project_tool: Any = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, project_tool: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._project_tool = project_tool

    def _run(self, expression: str) -> str:
        """Evaluate math expression (synchronous wrapper for CrewAI)."""
        if self._project_tool is None:
            return f"Calculation result for: {expression} (stub)"

        import asyncio

        try:
            result: ToolResult = asyncio.run(self._project_tool.execute(expression=expression))
            if result.success:
                data = result.data or {}
                return f"{data.get('expression', expression)} = {data.get('result', '')}"
            return f"Calculation failed: {result.error}"
        except Exception as e:
            return f"Calculation error: {e}"


class OCRTool(CrewBaseTool):
    """Extract text from images and scanned documents."""

    name: str = "ocr"
    description: str = "Extract text from images and scanned documents"

    _project_tool: Any = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, project_tool: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._project_tool = project_tool

    def _run(self, image_path: str) -> str:
        """Extract text from image (synchronous wrapper for CrewAI)."""
        if self._project_tool is None:
            return f"OCR text from {image_path} (stub)"

        import asyncio

        try:
            result: ToolResult = asyncio.run(self._project_tool.execute(image_path=image_path))
            if result.success:
                lines = result.data or []
                return "\n".join(line.get("text", "") for line in lines)
            return f"OCR failed: {result.error}"
        except Exception as e:
            return f"OCR error: {e}"


class VisionLLMTool(CrewBaseTool):
    """Analyze images using vision model."""

    name: str = "vision_llm"
    description: str = "Analyze images using vision model"

    _project_tool: Any = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, project_tool: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._project_tool = project_tool

    def _run(self, image_path: str, prompt: str = "Describe this image") -> str:
        """Analyze image (synchronous wrapper for CrewAI)."""
        if self._project_tool is None:
            return f"Vision analysis of {image_path}: {prompt} (stub)"

        import asyncio

        try:
            result: ToolResult = asyncio.run(
                self._project_tool.execute(image_path=image_path, prompt=prompt)
            )
            if result.success:
                return str(result.data)
            return f"Vision analysis failed: {result.error}"
        except Exception as e:
            return f"Vision error: {e}"


class CodeSearchTool(CrewBaseTool):
    """Search building codes and regulations."""

    name: str = "code_search"
    description: str = "Search building codes and regulations"

    _project_tool: Any = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, project_tool: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._project_tool = project_tool

    def _run(self, query: str) -> str:
        """Search codes (synchronous wrapper for CrewAI)."""
        if self._project_tool is None:
            return f"Code references for {query} (stub)"

        import asyncio

        try:
            result: ToolResult = asyncio.run(self._project_tool.execute(query=query))
            if result.success:
                return str(result.data)
            return f"Code search failed: {result.error}"
        except Exception as e:
            return f"Code search error: {e}"


class WeatherAPITool(CrewBaseTool):
    """Get weather forecast for construction planning."""

    name: str = "weather_api"
    description: str = "Get weather forecast for construction planning"

    def _run(self, location: str, date_range: str = "next 7 days") -> str:
        """Fetch weather data (stub implementation)."""
        return f"Weather for {location} in {date_range}: Clear skies, 28°C, no rain expected"
