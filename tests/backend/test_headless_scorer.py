"""Tests for the headless eval scorer (issue #859)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.eval.headless_scorer import (
    ALL_CATEGORIES,
    EVAL_SCORES_FILENAME,
    LLM_JUDGE_CATEGORIES,
    HeadlessScorer,
    compute_decision_log_hash,
)
from core.eval.headless_signals import (
    score_agency,
    score_economic_behavior,
    score_errors,
    score_internal_state,
    score_productivity,
    score_safety,
    score_social_dynamics,
    score_world_evolution,
)
from core.simulation.decision_logger import DecisionLogger, DecisionLogReader

# ─── Helpers ───────────────────────────────────────────────────


def _build_log(tmp_path: Path) -> Path:
    """Synthesize a small decision log exercising every event type."""
    logger = DecisionLogger(tmp_path)
    # Builds — 3 propose_build intents across 2 distinct structures.
    logger.log_tool_intent(
        actor_id="rex",
        tool_name="propose_build",
        args={"structure_type": "cabin"},
        status="executed",
    )
    logger.log_tool_intent(
        actor_id="rex",
        tool_name="propose_build",
        args={"structure_type": "watchtower"},
        status="simulated",
    )
    logger.log_tool_intent(
        actor_id="aurora",
        tool_name="propose_build",
        args={"structure_type": "cabin"},
        status="executed",
    )
    # A blocked intent for errors/safety.
    logger.log_tool_intent(
        actor_id="rex",
        tool_name="trade",
        args={},
        status="blocked",
        block_reason="management:high",
    )
    # An economic tool call.
    logger.log_tool_intent(
        actor_id="vera",
        tool_name="currency_transfer",
        args={"amount": 5},
        status="executed",
    )
    # Relationship + alliance deltas for social_dynamics.
    logger.log_relationship_delta(
        a="vera", b="rex", before={"trust": 0.5}, after={"trust": 0.7}, reason="praise"
    )
    logger.log_relationship_delta(
        a="vera", b="aurora", before={"trust": 0.5}, after={"trust": 0.4}, reason="snub"
    )
    logger.log_alliance_delta(
        alliance_id="builders",
        members=["rex", "aurora"],
        before={"members_count": 1},
        after={"members_count": 2},
    )
    # Goals for agency.
    logger.log_new_goal(actor_id="rex", description="ship cabin", source="dream")
    logger.log_new_goal(actor_id="aurora", description="paint mural", source="reflection")
    # Needs transitions for internal_state.
    logger.log_needs_state(actor_id="rex", hunger=0.4)
    logger.log_needs_state(actor_id="rex", hunger=0.7)
    logger.log_dream(actor_id="rex", dream_narrative="...", mood_shift="hopeful")
    # World event.
    logger.log_world_event(event_type="nightfall")
    # Utterances — a normal one + a management-channel one.
    logger.log_utterance(actor_id="rex", text="Let's build something together.")
    logger.log_utterance(
        actor_id="management",
        text="flagged: scale concern",
        channel="management",
    )
    logger.close()
    return tmp_path


def _write_metadata(folder: Path, scenario_path: Path | None = None) -> None:
    payload: dict[str, Any] = {
        "name": "synthetic",
        "scenario_id": "synthetic_test",
    }
    if scenario_path:
        payload["scenario"] = str(scenario_path)
    (folder / "metadata.json").write_text(json.dumps(payload))


# ─── Deterministic signal extractors ───────────────────────────


def test_world_evolution_counts_proposals_and_variety(tmp_path: Path) -> None:
    _build_log(tmp_path)
    rows = list(DecisionLogReader(tmp_path).replay())
    result = score_world_evolution(rows)
    assert result["score"] > 0
    assert result["sub_scores"]["proposal_count"] == 3.0
    assert result["sub_scores"]["structure_variety"] == 2.0
    # Evidence should reference real ticks from the log.
    assert all("tick" in e for e in result["evidence"])


def test_social_dynamics_includes_alliances_and_trust_magnitude(tmp_path: Path) -> None:
    _build_log(tmp_path)
    rows = list(DecisionLogReader(tmp_path).replay())
    result = score_social_dynamics(rows)
    assert result["score"] > 0
    assert result["sub_scores"]["relationship_delta_count"] == 2.0
    assert result["sub_scores"]["alliance_delta_count"] == 1.0
    # trust magnitude = |0.7-0.5| + |0.4-0.5| = 0.3
    assert result["sub_scores"]["trust_magnitude"] == pytest.approx(0.3, abs=1e-6)


def test_errors_uses_block_rate(tmp_path: Path) -> None:
    _build_log(tmp_path)
    rows = list(DecisionLogReader(tmp_path).replay())
    result = score_errors(rows)
    # 1 blocked out of 5 tool intents -> blocked_rate=0.2 -> score≈80
    assert result["sub_scores"]["blocked_count"] == 1.0
    assert result["sub_scores"]["total_tool_intents"] == 5.0
    assert result["sub_scores"]["blocked_rate"] == pytest.approx(0.2, abs=1e-6)
    assert result["score"] == pytest.approx(80.0, abs=1e-6)


def test_productivity_counts_completed_intents_per_agent(tmp_path: Path) -> None:
    _build_log(tmp_path)
    rows = list(DecisionLogReader(tmp_path).replay())
    result = score_productivity(rows)
    # 4 executed/simulated intents (excluding the blocked one).
    assert result["sub_scores"]["executed_count"] == 4.0
    # 3 distinct actors (rex, aurora, vera).
    assert result["sub_scores"]["distinct_actors"] == 3.0
    assert result["score"] > 0


def test_agency_uses_goal_sources(tmp_path: Path) -> None:
    _build_log(tmp_path)
    rows = list(DecisionLogReader(tmp_path).replay())
    result = score_agency(rows)
    assert result["sub_scores"]["goal_count"] == 2.0
    assert result["sub_scores"]["distinct_sources"] == 2.0
    assert result["sub_scores"]["distinct_actors"] == 2.0


def test_economic_behavior_picks_currency_tools(tmp_path: Path) -> None:
    _build_log(tmp_path)
    rows = list(DecisionLogReader(tmp_path).replay())
    result = score_economic_behavior(rows)
    # 'trade' (blocked) + 'currency_transfer' both match the economic vocabulary.
    assert result["sub_scores"]["economic_intent_count"] == 2.0
    assert result["sub_scores"]["distinct_actors"] == 2.0


def test_internal_state_counts_transitions(tmp_path: Path) -> None:
    _build_log(tmp_path)
    rows = list(DecisionLogReader(tmp_path).replay())
    result = score_internal_state(rows)
    # 1st snapshot is new (counts), 2nd differs (counts) -> 2 transitions.
    assert result["sub_scores"]["needs_transitions"] >= 1.0
    assert result["sub_scores"]["dream_count"] == 1.0
    assert result["sub_scores"]["mood_shift_count"] == 1.0


def test_safety_penalizes_high_severity_blocks(tmp_path: Path) -> None:
    _build_log(tmp_path)
    rows = list(DecisionLogReader(tmp_path).replay())
    result = score_safety(rows)
    assert result["sub_scores"]["blocked_count"] == 1.0
    # The single blocked entry uses severity="high" → score < 100.
    assert result["score"] < 100.0
    assert result["sub_scores"]["management_utterance_count"] == 1.0


# ─── compute_decision_log_hash ──────────────────────────────────


def test_compute_decision_log_hash_is_stable(tmp_path: Path) -> None:
    _build_log(tmp_path)
    log_path = tmp_path / "decision_log.jsonl"
    h1 = compute_decision_log_hash(log_path)
    h2 = compute_decision_log_hash(log_path)
    assert h1 == h2
    assert len(h1) == 64


# ─── HeadlessScorer ────────────────────────────────────────────


class _StubLLM:
    """Counts calls and returns a fixed JSON payload."""

    def __init__(self, content: str = '{"score": 73, "reasoning": "stub"}') -> None:
        self.content = content
        self.calls = 0

    async def complete(self, **kwargs: Any) -> Any:
        self.calls += 1

        class _Resp:
            def __init__(self, c: str) -> None:
                self.content = c
                self.input_tokens = 100
                self.output_tokens = 50
                self.estimated_cost = 0
                self.latency_ms = 10

        return _Resp(self.content)


@pytest.mark.asyncio
async def test_scorer_writes_output_and_includes_all_categories(tmp_path: Path) -> None:
    _build_log(tmp_path)
    _write_metadata(tmp_path)

    scorer = HeadlessScorer(tmp_path, llm_client=_StubLLM())
    result = await scorer.score()

    # File written + has expected top-level shape.
    output = json.loads((tmp_path / EVAL_SCORES_FILENAME).read_text())
    assert output["scorer"] == "headless"
    assert output["decision_log_hash"] == result["decision_log_hash"]
    assert output["scenario_id"] == "synthetic_test"

    # Every dashboard category appears.
    assert set(output["categories"].keys()) == set(ALL_CATEGORIES)

    # Categories have score + reasoning + signal_type.
    for cat, payload in output["categories"].items():
        assert "score" in payload
        assert "reasoning" in payload
        assert payload["signal_type"] in ("deterministic", "llm_judge", "unsupported")
        if cat in LLM_JUDGE_CATEGORIES:
            assert payload["signal_type"] == "llm_judge"


@pytest.mark.asyncio
async def test_scorer_caches_llm_judge_results(tmp_path: Path) -> None:
    _build_log(tmp_path)
    _write_metadata(tmp_path)

    stub = _StubLLM()
    scorer = HeadlessScorer(tmp_path, llm_client=stub)
    await scorer.score()
    first_call_count = stub.calls
    assert first_call_count > 0  # LLM categories ran.

    # Second invocation hits cache — no new LLM calls.
    scorer2 = HeadlessScorer(tmp_path, llm_client=stub)
    result2 = await scorer2.score()
    assert stub.calls == first_call_count

    for cat in LLM_JUDGE_CATEGORIES:
        assert result2["categories"][cat].get("cached") is True


@pytest.mark.asyncio
async def test_scorer_evaluates_success_criteria(tmp_path: Path) -> None:
    _build_log(tmp_path)

    # Author a scenario with eval_targets + a success criterion.
    scenario_path = tmp_path / "synthetic_test.yaml"
    scenario_path.write_text(
        """
meta:
  name: Synthetic
eval_targets:
  primary: [social_dynamics]
  secondary: [dialogue_quality]
  success_criteria:
    social_dynamics: "min_score >= 60"
"""
    )
    _write_metadata(tmp_path, scenario_path=scenario_path)

    stub = _StubLLM(content='{"pass": true, "reason": "alliances formed"}')
    scorer = HeadlessScorer(tmp_path, llm_client=stub)
    result = await scorer.score()

    assert result["primary"] == ["social_dynamics"]
    assert result["secondary"] == ["dialogue_quality"]
    assert len(result["success_criteria"]) == 1
    entry = result["success_criteria"][0]
    assert entry["category"] == "social_dynamics"
    assert entry["pass"] is True
    assert "alliances" in entry["reason"]


@pytest.mark.asyncio
async def test_scorer_routes_build_quality_through_deterministic(tmp_path: Path) -> None:
    """build_quality (#876) is dispatched with sim_folder; signal_type=deterministic."""
    _build_log(tmp_path)
    _write_metadata(tmp_path)

    # Drop a minimal new_buildings fixture so build_quality can compute a real score.
    from core.agents.build_intent import SizeClass, StructureType
    from core.minecraft.build_plan import (
        BoundingBox,
        BuildPlan,
        Footprint,
        Level,
        MaterialAssignment,
        Position3D,
    )
    from core.minecraft.build_script import BuildCommand, BuildScript

    plan = BuildPlan(
        structure_type=StructureType.cabin,
        size_class=SizeClass.small,
        source_image_id="src:1",
        footprint=Footprint(shape="rectangle", bbox=BoundingBox(x=0, y=0, w=4, h=4)),
        levels=[Level(index=0, height_blocks=3, floor_material="cobblestone")],
        materials=[MaterialAssignment(region="walls", material="oak_log")],
        decomposer_version=1,
        provider_model_id="test/decomposer",
    )
    script = BuildScript(
        intent_id="iq",
        structure_type=StructureType.cabin,
        size_class=SizeClass.small,
        origin=Position3D(x=0, y=64, z=0),
        commands=[
            BuildCommand(
                kind="fill",
                position=Position3D(x=0, y=65, z=0),
                region_to=Position3D(x=3, y=67, z=0),
                block_type="oak_log",
            )
        ],
        materials_manifest={},
        total_blocks=12,
        estimated_seconds=1.0,
        source_plan_hash="h",
        compiler_version=1,
    )
    intent_dir = tmp_path / "new_buildings" / "iq"
    (intent_dir / "decompositions").mkdir(parents=True)
    (intent_dir / "scripts").mkdir(parents=True)
    (intent_dir / "decompositions" / "iter_0.buildplan.json").write_text(
        plan.model_dump_json()
    )
    (intent_dir / "scripts" / "iter_0.script.json").write_text(
        json.dumps(script.to_jsonable())
    )
    (intent_dir / "final_summary.json").write_text(
        json.dumps(
            {
                "iterations": [
                    {
                        "iteration": 0,
                        "buildplan_path": (intent_dir / "decompositions" / "iter_0.buildplan.json")
                        .as_posix(),
                        "script_path": (intent_dir / "scripts" / "iter_0.script.json")
                        .as_posix(),
                    }
                ]
            }
        )
    )

    scorer = HeadlessScorer(tmp_path, llm_client=_StubLLM())
    result = await scorer.score()

    assert "build_quality" in result["categories"]
    payload = result["categories"]["build_quality"]
    assert payload["signal_type"] == "deterministic"
    assert payload["sub_scores"]["build_count"] == 1.0


@pytest.mark.asyncio
async def test_scorer_skips_llm_categories_when_no_client(tmp_path: Path) -> None:
    _build_log(tmp_path)
    _write_metadata(tmp_path)

    scorer = HeadlessScorer(tmp_path, llm_client=None)
    result = await scorer.score()

    for cat in LLM_JUDGE_CATEGORIES:
        payload = result["categories"][cat]
        assert payload.get("skipped") is True
        assert payload["score"] == 0.0


@pytest.mark.asyncio
async def test_faction_emergence_signals_are_non_trivial(tmp_path: Path) -> None:
    """Acceptance: social_dynamics/world_evolution score non-trivially on faction_emergence_test-like input."""
    # Simulate the kind of activity faction_emergence_test would produce:
    # multiple build proposals, alliance formation, many relationship deltas.
    logger = DecisionLogger(tmp_path)
    for kind in ("cabin", "wall", "watchtower"):
        logger.log_tool_intent(
            actor_id="rex",
            tool_name="propose_build",
            args={"structure_type": kind},
            status="executed",
        )
    logger.log_alliance_delta(
        alliance_id="builders",
        members=["rex", "aurora"],
        before={"members_count": 1},
        after={"members_count": 2},
    )
    logger.log_alliance_delta(
        alliance_id="skeptics",
        members=["fork", "sentinel"],
        before={"members_count": 1},
        after={"members_count": 2},
    )
    for _ in range(6):
        logger.log_relationship_delta(
            a="rex", b="aurora",
            before={"trust": 0.5}, after={"trust": 0.7},
            reason="collab",
        )
    logger.close()

    _write_metadata(tmp_path)
    rows = list(DecisionLogReader(tmp_path).replay())

    we = score_world_evolution(rows)
    sd = score_social_dynamics(rows)
    assert we["score"] >= 50.0
    assert sd["score"] >= 50.0
