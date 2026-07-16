"""Test all tools load and basic execution."""

import asyncio
import sys


async def main() -> None:
    errors = []

    # Import all tools
    try:
        from civilmind.tools.base import BaseTool, ToolResult
        from civilmind.tools.calculator import CalculatorTool
        from civilmind.tools.code_search import CodeSearchTool
        from civilmind.tools.ocr import OCRTool
        from civilmind.tools.registry import ToolRegistry
        from civilmind.tools.sql_query import SQLQueryTool
        from civilmind.tools.vector_search import VectorSearchTool
        from civilmind.tools.vision_llm import VisionLLMTool
    except ImportError as e:
        print(f"[FAIL] Import error: {e}")
        sys.exit(1)

    # Register all tools
    r = ToolRegistry()
    tools = [
        VectorSearchTool(),
        SQLQueryTool(),
        OCRTool(),
        VisionLLMTool(),
        CalculatorTool(),
        CodeSearchTool(),
    ]

    for tool in tools:
        r.register(tool)

    expected = {
        "vector_search": "retrieval",
        "sql_query": "data",
        "ocr": "vision",
        "vision_llm": "vision",
        "calculator": "calculation",
        "code_search": "knowledge",
    }

    # Verify registration
    for name, cat in expected.items():
        if not r.has(name):
            errors.append(f"Tool '{name}' not registered")
            continue
        t = r.get(name)
        if t.category != cat:
            errors.append(f"Tool '{name}' category mismatch: {t.category} != {cat}")

    # Test calculator (no external deps)
    calc = CalculatorTool()
    result = await calc.execute(expression="2 + 2")
    if not result.success or result.data["result"] != 4:
        errors.append(f"Calculator failed: {result.error}")

    # Test code_search (no external deps)
    cs = CodeSearchTool()
    result = await cs.execute(query="sprinkler")
    if not result.success or len(result.data) == 0:
        errors.append(f"CodeSearch failed: {result.error}")

    # Print results
    for name in sorted(expected.keys()):
        t = r.get(name)
        print(f"  [OK] {name} ({t.category}): {t.description}")

    if errors:
        print(f"\n  [FAIL] {len(errors)} error(s):")
        for e in errors:
            print(f"    - {e}")
        sys.exit(1)
    else:
        print(f"\n  All {len(expected)} tools loaded and verified")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
