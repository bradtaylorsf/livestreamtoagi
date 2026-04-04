"""Eval engine — runs LLM-based evaluations against simulation data."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from core.eval.loader import load_simulation_data, organize_by_category
from core.eval.prompt_loader import discover_categories, load_prompt, render_user_prompt

# Categories selected for the "quick" eval suite — hand-picked for breadth
# rather than relying on alphabetical order of available categories.
QUICK_CATEGORIES = ["entertainment", "safety", "errors"]

if TYPE_CHECKING:
    import uuid

    from core.database import Database
    from core.llm_client import OpenRouterClient
    from core.repos.eval_repo import EvalRepo

logger = logging.getLogger(__name__)


class EvalEngine:
    """Runs eval categories against a simulation and stores results."""

    def __init__(
        self,
        db: Database,
        llm_client: OpenRouterClient,
        eval_repo: EvalRepo,
    ) -> None:
        self._db = db
        self._llm = llm_client
        self._eval_repo = eval_repo

    async def run(
        self,
        simulation_id: uuid.UUID,
        *,
        categories: list[str] | None = None,
        suite: str = "full",
    ) -> uuid.UUID:
        """Run evals and return the eval_run_id."""
        # Create eval run record
        eval_run = await self._eval_repo.create_eval_run(simulation_id, suite)
        run_id = eval_run.id

        # Load simulation data
        try:
            data = await load_simulation_data(self._db, simulation_id)
        except ValueError as exc:
            await self._eval_repo.update_eval_run(
                run_id, status="failed", completed_at=datetime.now(UTC)
            )
            raise exc

        category_data = organize_by_category(data)

        # Determine which categories to run
        available = discover_categories()
        if categories:
            to_run = [c for c in categories if c in available]
        elif suite == "quick":
            to_run = [c for c in QUICK_CATEGORIES if c in available]
        else:
            to_run = available

        total_cost = Decimal("0")
        total_scores: list[Decimal] = []
        had_failure = False

        for cat in to_run:
            try:
                result = await self._run_category(
                    run_id, cat, category_data.get(cat, {}), data
                )
                if result["score"] is not None:
                    total_scores.append(result["score"])
                total_cost += result["cost"]
            except Exception:
                logger.exception("Eval category '%s' failed", cat)
                had_failure = True
                # Save a failed result so it's visible
                await self._eval_repo.save_eval_result(
                    eval_run_id=run_id,
                    category=cat,
                    score=Decimal("0"),
                    reasoning="Eval failed — see logs for details",
                    evidence=None,
                    sub_scores=None,
                    tokens_used=0,
                    cost=Decimal("0"),
                )

        # Compute overall score
        overall = (
            sum(total_scores) / len(total_scores)
            if total_scores
            else None
        )

        status = "completed" if not had_failure else (
            "completed" if total_scores else "failed"
        )

        await self._eval_repo.update_eval_run(
            run_id,
            status=status,
            overall_score=overall,
            cost=total_cost,
            completed_at=datetime.now(UTC),
        )

        return run_id

    async def _run_category(
        self,
        run_id: uuid.UUID,
        category: str,
        cat_data: dict[str, Any],
        full_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Run a single eval category and store the result."""
        prompt_config = load_prompt(category)

        model = prompt_config.get("model", "claude-sonnet-4-6")
        max_tokens = prompt_config.get("max_tokens", 4096)
        temperature = prompt_config.get("temperature", 0.3)

        system_prompt = prompt_config["system"]
        user_prompt = render_user_prompt(prompt_config, cat_data)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = await self._llm.complete(
            messages=messages,
            model=model,
            agent_id="eval_engine",
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=120.0,
        )

        # Capture cost immediately so it's never lost on parse failure
        tokens_used = response.input_tokens + response.output_tokens
        cost = response.estimated_cost

        try:
            parsed = _parse_eval_response(response.content)
            score = Decimal(str(parsed.get("score", 0)))
            reasoning = parsed.get("reasoning", "")
            evidence = parsed.get("evidence")
            sub_scores = parsed.get("sub_scores")
        except Exception:
            logger.exception("Failed to parse eval response for '%s'", category)
            score = Decimal("0")
            reasoning = f"Parse failed — raw response: {response.content[:500]}"
            evidence = None
            sub_scores = None

        await self._eval_repo.save_eval_result(
            eval_run_id=run_id,
            category=category,
            score=score,
            reasoning=reasoning,
            evidence=evidence,
            sub_scores=sub_scores,
            tokens_used=tokens_used,
            cost=cost,
        )

        return {
            "score": score,
            "cost": cost,
            "tokens_used": tokens_used,
        }


def _parse_eval_response(content: str) -> dict[str, Any]:
    """Extract JSON from LLM response, handling markdown code fences."""
    text = content.strip()

    # Try to extract JSON from code fence
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("{"):
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError:
                    continue

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Last resort: find first { to last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse eval response as JSON, returning raw")
    return {"score": 0, "reasoning": content, "evidence": None, "sub_scores": None}
