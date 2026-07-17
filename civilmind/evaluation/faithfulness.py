"""Faithfulness checker — LLM-as-judge for generation quality.

Evaluates whether an LLM answer is grounded in the provided context,
detects hallucinations, and scores answer relevance to the query.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from civilmind.llm.client import LLMClient, LLMMessage

logger = structlog.get_logger()

JUDGE_SYSTEM_PROMPT = """You are a strict evaluation judge for a construction knowledge system.

You will be given:
1. A user question
2. Context documents used to answer the question
3. The generated answer

Evaluate the answer on these criteria:
- Faithfulness: Is every claim in the answer supported by the context?
- Relevance: Does the answer directly address the question?
- Completeness: Does the answer cover all aspects of the question?

Return your evaluation as JSON:
{
  "faithfulness_score": <0.0 to 1.0>,
  "relevance_score": <0.0 to 1.0>,
  "completeness_score": <0.0 to 1.0>,
  "overall_score": <0.0 to 1.0>,
  "hallucinated_claims": ["claim1", "claim2"],
  "missing_aspects": ["aspect1", "aspect2"],
  "explanation": "Brief explanation of the evaluation"
}

Be strict. A score above 0.8 means well-grounded. Below 0.5 means significant issues.
"""


@dataclass
class FaithfulnessResult:
    """Result of a faithfulness evaluation."""

    faithfulness_score: float = 0.0
    relevance_score: float = 0.0
    completeness_score: float = 0.0
    overall_score: float = 0.0
    hallucinated_claims: list[str] = field(default_factory=list)
    missing_aspects: list[str] = field(default_factory=list)
    explanation: str = ""

    @property
    def is_faithful(self) -> bool:
        """True if faithfulness score is above threshold."""
        return self.faithfulness_score >= 0.7

    @property
    def summary(self) -> dict[str, Any]:
        """Return as a flat dict for logging/storage."""
        return {
            "faithfulness_score": self.faithfulness_score,
            "relevance_score": self.relevance_score,
            "completeness_score": self.completeness_score,
            "overall_score": self.overall_score,
            "hallucinated_claims": self.hallucinated_claims,
            "missing_aspects": self.missing_aspects,
            "explanation": self.explanation,
        }


class FaithfulnessChecker:
    """LLM-as-judge for answer faithfulness and quality.

    Uses the project's LLM to evaluate generated answers against context.

    Usage:
        checker = FaithfulnessChecker(llm)
        result = await checker.evaluate(query, context, answer)
        if not result.is_faithful:
            print(f"Hallucinations: {result.hallucinated_claims}")
    """

    def __init__(
        self,
        llm: LLMClient,
        threshold: float = 0.7,
    ) -> None:
        """Initialize with LLM client.

        Args:
            llm: LLM client for judge evaluation.
            threshold: Minimum faithfulness score to pass.
        """
        self._llm = llm
        self._threshold = threshold

    async def evaluate(
        self,
        query: str,
        context: str,
        answer: str,
    ) -> FaithfulnessResult:
        """Evaluate answer faithfulness.

        Args:
            query: Original user question.
            context: Context documents used for generation.
            answer: Generated answer to evaluate.

        Returns:
            FaithfulnessResult with scores and details.
        """
        user_prompt = f"""## Question
{query}

## Context
{context}

## Answer
{answer}

Evaluate the answer above. Return ONLY valid JSON."""

        try:
            result = await self._llm.chat(
                messages=[LLMMessage(role="user", content=user_prompt)],
                system_prompt=JUDGE_SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=1000,
            )

            parsed = _parse_judge_response(result.content)

            faith_result = FaithfulnessResult(
                faithfulness_score=parsed.get("faithfulness_score", 0.0),
                relevance_score=parsed.get("relevance_score", 0.0),
                completeness_score=parsed.get("completeness_score", 0.0),
                overall_score=parsed.get("overall_score", 0.0),
                hallucinated_claims=parsed.get("hallucinated_claims", []),
                missing_aspects=parsed.get("missing_aspects", []),
                explanation=parsed.get("explanation", ""),
            )

            logger.info(
                "Faithfulness evaluation complete",
                faithfulness=round(faith_result.faithfulness_score, 3),
                relevance=round(faith_result.relevance_score, 3),
                is_faithful=faith_result.is_faithful,
            )

            return faith_result

        except Exception as e:
            logger.error("Faithfulness evaluation failed", error=str(e))
            return FaithfulnessResult(explanation=f"Evaluation failed: {e}")

    async def batch_evaluate(
        self,
        evaluations: list[dict[str, str]],
    ) -> list[FaithfulnessResult]:
        """Evaluate multiple (query, context, answer) triples.

        Args:
            evaluations: List of {"query": ..., "context": ..., "answer": ...}.

        Returns:
            List of FaithfulnessResult, one per evaluation.
        """
        results: list[FaithfulnessResult] = []
        for ev in evaluations:
            result = await self.evaluate(
                query=ev["query"],
                context=ev["context"],
                answer=ev["answer"],
            )
            results.append(result)
        return results


def _parse_judge_response(content: str) -> dict[str, Any]:
    """Parse LLM judge response JSON. Handles markdown code blocks."""
    import json

    text = content.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (```json and ```)
        lines = [line for line in lines[1:] if not line.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        logger.warning("Failed to parse judge response", content=text[:200])
        return {}
