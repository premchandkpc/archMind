"""Tool registry — central catalog of all available tools.

Agents look up tools by name. The registry handles registration,
retrieval, and listing. A global instance is provided for convenience.
"""

from __future__ import annotations

import structlog

from civilmind.tools.base import BaseTool

logger = structlog.get_logger()


class ToolRegistry:
    """Central registry for all tool instances.

    Usage:
        registry = ToolRegistry()
        registry.register(VectorSearchTool(...))
        tool = registry.get("vector_search")
        result = await tool.execute(query="M25 concrete")
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool. Overwrites if name already exists."""
        if tool.name in self._tools:
            logger.warning(
                "Overwriting existing tool",
                name=tool.name,
                old=self._tools[tool.name].__class__.__name__,
                new=tool.__class__.__name__,
            )
        self._tools[tool.name] = tool
        logger.debug("Registered tool", name=tool.name, category=tool.category)

    def get(self, name: str) -> BaseTool:
        """Get tool by name. Raises KeyError if not found."""
        if name not in self._tools:
            available = ", ".join(sorted(self._tools.keys()))
            raise KeyError(f"Unknown tool '{name}'. Available: {available}")
        return self._tools[name]

    def has(self, name: str) -> bool:
        """Check if tool is registered."""
        return name in self._tools

    def list_tools(self) -> list[dict[str, str]]:
        """List all registered tools with metadata."""
        return [
            {"name": t.name, "description": t.description, "category": t.category}
            for t in self._tools.values()
        ]

    def list_by_category(self, category: str) -> list[BaseTool]:
        """Filter tools by category."""
        return [t for t in self._tools.values() if t.category == category]

    def clear(self) -> None:
        """Remove all tools. Used in testing."""
        self._tools.clear()


# Global registry instance
registry = ToolRegistry()
