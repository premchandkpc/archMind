"""CalculatorTool — safe mathematical expression evaluator.

Uses AST parsing to prevent arbitrary code execution.
No eval() — only arithmetic, functions, and constants allowed.
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

import structlog

from civilmind.tools.base import BaseTool, ToolResult

logger = structlog.get_logger()

# Allowed operators
SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Allowed math functions
SAFE_FUNCS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "inf": math.inf,
}


def safe_eval(node: ast.AST) -> Any:
    """Recursively evaluate an AST node with only safe operations."""
    if isinstance(node, ast.Expression):
        return safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, complex)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value).__name__}")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in SAFE_OPS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        return SAFE_OPS[op_type](safe_eval(node.left), safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in SAFE_OPS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        return SAFE_OPS[op_type](safe_eval(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only direct function calls allowed")
        func_name = node.func.id
        if func_name not in SAFE_FUNCS:
            raise ValueError(f"Unknown function: {func_name}")
        func = SAFE_FUNCS[func_name]
        if callable(func):
            args = [safe_eval(arg) for arg in node.args]
            return func(*args)
        return func
    if isinstance(node, ast.Name):
        if node.id in SAFE_FUNCS:
            val = SAFE_FUNCS[node.id]
            if not callable(val):
                return val
            raise ValueError(f"'{node.id}' is a function, not a constant")
        raise ValueError(f"Unknown name: {node.id}")
    raise ValueError(f"Unsupported expression: {type(node).__name__}")


class CalculatorTool(BaseTool):
    """Safe mathematical expression evaluator."""

    name = "calculator"
    description = "Perform mathematical calculations"
    category = "calculation"

    async def execute(
        self,
        expression: str,
        **kwargs: Any,
    ) -> ToolResult:
        """Evaluate a mathematical expression safely.

        Args:
            expression: Math expression like "sqrt(144) + 2**10".

        Returns:
            ToolResult with the numeric result.
        """
        try:
            tree = ast.parse(expression, mode="eval")
            result = safe_eval(tree)

            logger.info(
                "Calculation completed",
                expression=expression,
                result=result,
            )

            return ToolResult(
                success=True,
                data={"expression": expression, "result": result},
                metadata={"type": type(result).__name__},
            )

        except (ValueError, TypeError, ZeroDivisionError) as e:
            return ToolResult(
                success=False,
                error=f"Calculation error: {e}",
            )
        except SyntaxError as e:
            return ToolResult(
                success=False,
                error=f"Invalid expression syntax: {e}",
            )
        except Exception as e:
            logger.error("Calculator failed", expression=expression, error=str(e))
            return ToolResult(
                success=False,
                error=f"{type(e).__name__}: {e}",
            )
