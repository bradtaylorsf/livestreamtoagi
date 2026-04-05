"""Tests for eval analyzer (#241)."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from datetime import datetime, UTC

from core.models import (
    AnalysisResult,
    EvalAnalysis,
    ProposedChange,
)


# ── Model tests ──────────────────────────────────────────────


class TestAnalysisResultModel:
    def test_create(self) -> None:
        result = AnalysisResult(
            summary="Test summary",
            confidence=0.8,
            proposals=[
                ProposedChange(
                    type="param_change",
                    agent_id="rex",
                    param_path="chattiness",
                    current_value=0.4,
                    proposed_value=0.3,
                    reasoning="Rex talks too much",
                ),
            ],
        )
        assert result.confidence == 0.8
        assert len(result.proposals) == 1
        assert result.proposals[0].type == "param_change"

    def test_defaults(self) -> None:
        result = AnalysisResult()
        assert result.summary == ""
        assert result.confidence == 0.0
        assert result.proposals == []


class TestProposedChangeModel:
    def test_prompt_change(self) -> None:
        p = ProposedChange(
            type="prompt_change",
            agent_id="aurora",
            section="personality",
            current_text="Old text",
            proposed_text="New text",
            reasoning="Needs more creativity",
        )
        assert p.type == "prompt_change"
        assert p.agent_id == "aurora"

    def test_technical_issue(self) -> None:
        p = ProposedChange(
            type="technical_issue",
            title="Tool fails intermittently",
            body="The execute_code tool fails 30% of the time",
            labels=["bug", "eval-finding"],
            severity="high",
            reasoning="Multiple eval runs show tool failures",
        )
        assert p.type == "technical_issue"
        assert p.severity == "high"


# ── Safety rails tests ───────────────────────────────────────


class TestSafetyRails:
    def test_param_delta_clamped(self) -> None:
        from core.eval.analyzer import _apply_safety_rails

        proposals = [
            {
                "type": "param_change",
                "agent_id": "rex",
                "param_path": "chattiness",
                "current_value": 0.4,
                "proposed_value": 0.9,  # Delta of 0.5 — too large
                "reasoning": "Rex needs to talk more",
            }
        ]
        result = _apply_safety_rails(proposals)
        assert len(result) == 1
        assert result[0]["proposed_value"] == pytest.approx(0.5)  # Clamped to 0.4 + 0.1
        assert "Clamped" in result[0]["reasoning"]

    def test_small_delta_passes(self) -> None:
        from core.eval.analyzer import _apply_safety_rails

        proposals = [
            {
                "type": "param_change",
                "agent_id": "rex",
                "param_path": "chattiness",
                "current_value": 0.4,
                "proposed_value": 0.35,  # Delta of 0.05 — fine
                "reasoning": "Slight reduction",
            }
        ]
        result = _apply_safety_rails(proposals)
        assert result[0]["proposed_value"] == 0.35
        assert "Clamped" not in result[0]["reasoning"]

    def test_prompt_change_passes_through(self) -> None:
        from core.eval.analyzer import _apply_safety_rails

        proposals = [
            {
                "type": "prompt_change",
                "agent_id": "aurora",
                "proposed_text": "Be more creative",
                "reasoning": "Low creativity scores",
            }
        ]
        result = _apply_safety_rails(proposals)
        assert len(result) == 1
        assert result[0]["proposed_text"] == "Be more creative"


# ── JSON parsing tests ───────────────────────────────────────


class TestParseAnalysisResponse:
    def test_parse_clean_json(self) -> None:
        from core.eval.analyzer import _parse_analysis_response

        data = {
            "summary": "All good",
            "confidence": 0.8,
            "proposals": [],
        }
        result = _parse_analysis_response(json.dumps(data))
        assert result["summary"] == "All good"
        assert result["confidence"] == 0.8

    def test_parse_json_in_code_fence(self) -> None:
        from core.eval.analyzer import _parse_analysis_response

        content = '```json\n{"summary": "Test", "confidence": 0.5, "proposals": []}\n```'
        result = _parse_analysis_response(content)
        assert result["summary"] == "Test"

    def test_parse_failure_returns_default(self) -> None:
        from core.eval.analyzer import _parse_analysis_response

        result = _parse_analysis_response("not json at all")
        assert result["confidence"] == 0.0
        assert result["proposals"] == []


# ── ChangeApplier tests ──────────────────────────────────────


class TestChangeApplier:
    @pytest.mark.asyncio
    async def test_set_nested(self) -> None:
        from core.eval.change_applier import _set_nested

        d: dict = {"a": {"b": 1}}
        _set_nested(d, "a.b", 2)
        assert d["a"]["b"] == 2

    @pytest.mark.asyncio
    async def test_set_nested_creates_missing_keys(self) -> None:
        from core.eval.change_applier import _set_nested

        d: dict = {}
        _set_nested(d, "a.b.c", 42)
        assert d["a"]["b"]["c"] == 42


# ── EvalAnalyzer integration test ────────────────────────────


class TestEvalAnalyzerUnit:
    @pytest.mark.asyncio
    async def test_analyze_returns_result(self) -> None:
        from core.eval.analyzer import EvalAnalyzer
        from core.models import EvalResult, EvalRun

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()

        mock_eval_repo = AsyncMock()
        run_id = uuid.uuid4()
        sim_id = uuid.uuid4()

        mock_eval_repo.get_eval_run.return_value = EvalRun(
            id=run_id,
            simulation_id=sim_id,
            eval_suite="quick",
            status="completed",
            started_at=datetime.now(UTC),
            overall_score=Decimal("65"),
        )
        mock_eval_repo.get_eval_results.return_value = [
            EvalResult(
                id=uuid.uuid4(),
                eval_run_id=run_id,
                category="entertainment",
                score=Decimal("70"),
                reasoning="Good but could be funnier",
                sub_scores={"humor": 60, "personality": 80},
            ),
        ]
        mock_eval_repo.get_eval_runs.return_value = []

        mock_llm = AsyncMock()
        mock_llm.complete.return_value = MagicMock(
            content=json.dumps({
                "summary": "Entertainment needs improvement",
                "confidence": 0.7,
                "proposals": [
                    {
                        "type": "prompt_change",
                        "agent_id": "grok",
                        "section": "personality",
                        "proposed_text": "Be funnier",
                        "reasoning": "Humor scores are low",
                    }
                ],
            }),
            input_tokens=1000,
            output_tokens=500,
            estimated_cost=Decimal("0.01"),
        )

        analyzer = EvalAnalyzer(db=mock_db, eval_repo=mock_eval_repo, llm_client=mock_llm)
        result = await analyzer.analyze(run_id)

        assert result.confidence == 0.7
        assert len(result.proposals) == 1
        assert result.proposals[0].type == "prompt_change"
        assert result.proposals[0].agent_id == "grok"

    @pytest.mark.asyncio
    async def test_analyze_empty_results(self) -> None:
        from core.eval.analyzer import EvalAnalyzer
        from core.models import EvalRun

        mock_db = AsyncMock()
        mock_eval_repo = AsyncMock()
        run_id = uuid.uuid4()

        mock_eval_repo.get_eval_run.return_value = EvalRun(
            id=run_id,
            simulation_id=uuid.uuid4(),
            eval_suite="quick",
            status="completed",
            started_at=datetime.now(UTC),
        )
        mock_eval_repo.get_eval_results.return_value = []

        mock_llm = AsyncMock()

        analyzer = EvalAnalyzer(db=mock_db, eval_repo=mock_eval_repo, llm_client=mock_llm)
        result = await analyzer.analyze(run_id)

        assert result.confidence == 0.0
        assert len(result.proposals) == 0
        mock_llm.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_analyze_not_found_raises(self) -> None:
        from core.eval.analyzer import EvalAnalyzer

        mock_db = AsyncMock()
        mock_eval_repo = AsyncMock()
        mock_eval_repo.get_eval_run.return_value = None
        mock_llm = AsyncMock()

        analyzer = EvalAnalyzer(db=mock_db, eval_repo=mock_eval_repo, llm_client=mock_llm)
        with pytest.raises(ValueError, match="not found"):
            await analyzer.analyze(uuid.uuid4())
