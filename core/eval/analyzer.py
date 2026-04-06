"""Eval analyzer — classifies findings into prompt changes vs technical issues.

Reads eval results, compares across runs, and produces actionable change
proposals via LLM-powered analysis.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from core.models import AnalysisResult, ProposedChange

if TYPE_CHECKING:
    import uuid

    from core.database import Database
    from core.llm_client import OpenRouterClient
    from core.repos.eval_repo import EvalRepo

logger = logging.getLogger(__name__)

ANALYZER_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "evals" / "prompts" / "_analyzer.yaml"
)

# Safety rails
MAX_PARAM_DELTA = 0.1
MAX_PROMPT_TOKEN_DELTA = 200
MIN_CONFIDENCE_THRESHOLD = 0.6


class EvalAnalyzer:
    """Analyzes eval results and proposes actionable changes."""

    def __init__(
        self,
        db: Database,
        eval_repo: EvalRepo,
        llm_client: OpenRouterClient,
        simulation_id: object | None = None,
    ) -> None:
        self._db = db
        self._eval_repo = eval_repo
        self._llm = llm_client
        self._simulation_id = simulation_id

    async def analyze(self, eval_run_id: uuid.UUID) -> AnalysisResult:
        """Analyze eval results and return classified change proposals.

        1. Load eval results for this run
        2. Load previous run results for trend comparison
        3. Send to LLM with structured output schema
        4. Parse and validate proposals
        5. Store analysis in DB
        6. Return result
        """
        # Load current eval results
        current_run = await self._eval_repo.get_eval_run(eval_run_id)
        if current_run is None:
            raise ValueError(f"Eval run {eval_run_id} not found")

        current_results = await self._eval_repo.get_eval_results(eval_run_id)
        if not current_results:
            return AnalysisResult(
                summary="No eval results to analyze.",
                confidence=0.0,
            )

        # Load previous runs for comparison
        previous_runs = await self._eval_repo.get_eval_runs(current_run.simulation_id)
        previous_results: list[dict[str, Any]] = []
        for run in previous_runs[:3]:  # Last 3 runs
            if run.id == eval_run_id:
                continue
            results = await self._eval_repo.get_eval_results(run.id)
            previous_results.append({
                "run_id": str(run.id),
                "overall_score": float(run.overall_score) if run.overall_score else None,
                "results": [
                    {
                        "category": r.category,
                        "score": float(r.score) if r.score else None,
                        "reasoning": r.reasoning,
                        "sub_scores": r.sub_scores,
                    }
                    for r in results
                ],
            })

        # Build the analysis prompt
        prompt_config = _load_analyzer_prompt()
        system_prompt = prompt_config["system"]

        user_data = _build_user_prompt(current_run, current_results, previous_results)

        # Call LLM
        response = await self._llm.complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_data},
            ],
            model=prompt_config.get("model", "claude-sonnet-4-6"),
            agent_id="eval_analyzer",
            temperature=prompt_config.get("temperature", 0.3),
            max_tokens=prompt_config.get("max_tokens", 8192),
            simulation_id=self._simulation_id,
        )

        # Parse response
        parsed = _parse_analysis_response(response.content)

        # Validate and filter proposals through safety rails
        validated_proposals = _apply_safety_rails(parsed.get("proposals", []))

        result = AnalysisResult(
            summary=parsed.get("summary", ""),
            confidence=float(parsed.get("confidence", 0.0)),
            proposals=[ProposedChange(**p) for p in validated_proposals],
            trend_data={
                "previous_runs": len(previous_results),
                "current_overall": float(current_run.overall_score) if current_run.overall_score else None,
                "is_first_run": len(previous_results) == 0,
            },
        )

        # Store in DB
        await self._store_analysis(eval_run_id, result)

        return result

    async def _store_analysis(
        self, eval_run_id: uuid.UUID, result: AnalysisResult
    ) -> None:
        """Store analysis results in the eval_analyses table."""
        try:
            await self._db.execute(
                """INSERT INTO eval_analyses
                   (eval_run_id, summary, confidence, proposals, trend_data)
                   VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)""",
                eval_run_id,
                result.summary,
                Decimal(str(result.confidence)),
                json.dumps([p.model_dump() for p in result.proposals]),
                json.dumps(result.trend_data) if result.trend_data else None,
            )
        except Exception:
            logger.exception("Failed to store eval analysis")

    async def get_analysis(self, eval_run_id: uuid.UUID) -> AnalysisResult | None:
        """Retrieve a stored analysis for an eval run."""
        row = await self._db.fetchrow(
            "SELECT * FROM eval_analyses WHERE eval_run_id = $1 ORDER BY created_at DESC LIMIT 1",
            eval_run_id,
        )
        if row is None:
            return None

        d = dict(row)
        proposals_raw = d.get("proposals", [])
        if isinstance(proposals_raw, str):
            proposals_raw = json.loads(proposals_raw)

        return AnalysisResult(
            summary=d.get("summary", ""),
            confidence=float(d.get("confidence", 0.0)),
            proposals=[ProposedChange(**p) for p in proposals_raw],
            trend_data=d.get("trend_data"),
        )


def _load_analyzer_prompt() -> dict[str, Any]:
    """Load the analyzer meta-prompt from YAML."""
    with open(ANALYZER_PROMPT_PATH) as f:
        return yaml.safe_load(f)


def _build_user_prompt(
    current_run: Any,
    current_results: list[Any],
    previous_results: list[dict[str, Any]],
) -> str:
    """Build the user message for the analyzer LLM call."""
    parts: list[str] = []

    parts.append("## Current Eval Results")
    parts.append(f"Overall Score: {current_run.overall_score}")
    parts.append(f"Suite: {current_run.eval_suite}")
    parts.append("")

    for r in current_results:
        parts.append(f"### {r.category}: {r.score}/100")
        if r.reasoning:
            parts.append(f"Reasoning: {r.reasoning}")
        if r.sub_scores:
            parts.append(f"Sub-scores: {json.dumps(r.sub_scores)}")
        if r.evidence:
            parts.append(f"Evidence: {json.dumps(r.evidence, default=str)}")
        parts.append("")

    if previous_results:
        parts.append("## Previous Run Comparison")
        for prev in previous_results:
            parts.append(f"Run {prev['run_id'][:8]}: Overall={prev['overall_score']}")
            for pr in prev["results"]:
                parts.append(f"  {pr['category']}: {pr['score']}")
            parts.append("")
    else:
        parts.append("## First Run — No Previous Data")
        parts.append(
            "This is the first eval run. There is no prior data for trend analysis."
        )
        parts.append(
            "Score based on absolute quality of current results only. "
            "Focus on identifying the most impactful improvements rather than trends."
        )
        parts.append("")

    parts.append("## Instructions")
    parts.append("Analyze these results and propose specific, actionable changes.")
    parts.append("Classify each proposal as prompt_change, param_change, "
                 "conversation_config_change, or technical_issue.")
    parts.append("Be conservative — small targeted changes are better than sweeping rewrites.")

    return "\n".join(parts)


def _parse_analysis_response(content: str) -> dict[str, Any]:
    """Extract JSON from analyzer LLM response."""
    text = content.strip()

    # Handle code fences
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

    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse analyzer response as JSON")
    return {"summary": "Analysis failed — could not parse response", "confidence": 0.0, "proposals": []}


def _apply_safety_rails(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter and constrain proposals through safety rails."""
    validated: list[dict[str, Any]] = []

    for p in proposals:
        proposal_type = p.get("type", "")

        if proposal_type == "param_change":
            # Enforce max param delta
            current = p.get("current_value")
            proposed = p.get("proposed_value")
            if isinstance(current, (int, float)) and isinstance(proposed, (int, float)):
                delta = abs(proposed - current)
                if delta > MAX_PARAM_DELTA:
                    # Clamp to max delta
                    direction = 1 if proposed > current else -1
                    p["proposed_value"] = current + (direction * MAX_PARAM_DELTA)
                    p["reasoning"] = (
                        f"{p.get('reasoning', '')} "
                        f"[Clamped from {proposed} to {p['proposed_value']} — "
                        f"max delta ±{MAX_PARAM_DELTA}]"
                    )

        validated.append(p)

    return validated
