"""FastAPI dependencies for tool injection.

Usage in endpoints:
    from civilmind.tools.dependencies import get_tool_registry
    from civilmind.tools.registry import ToolRegistry

    @router.get("/tools")
    async def list_tools(registry: ToolRegistry = Depends(get_tool_registry)):
        return registry.list_tools()
"""

from __future__ import annotations

from civilmind.tools.registry import ToolRegistry, registry


async def get_tool_registry() -> ToolRegistry:
    """Return the global tool registry."""
    return registry
