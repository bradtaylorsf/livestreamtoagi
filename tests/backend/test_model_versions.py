"""Tests for model version tracking (#316)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from core.llm_client import MODEL_NAME_ALIASES, MODEL_REGISTRY, OpenRouterClient
from core.models import EvalRun, EvalRunDetail, Simulation, SimulationCreate


class TestSimulationModelVersions:
    def test_simulation_create_has_model_versions(self):
        sim = SimulationCreate(
            name="test",
            config={},
            model_versions={
                "vera": {
                    "conversation": "anthropic/claude-haiku-4.5",
                    "building": "anthropic/claude-sonnet-4.6",
                },
            },
        )
        assert sim.model_versions["vera"]["conversation"] == "anthropic/claude-haiku-4.5"

    def test_simulation_create_defaults_empty(self):
        sim = SimulationCreate(name="test", config={})
        assert sim.model_versions == {}

    def test_simulation_model_has_model_versions(self):
        sim = Simulation(
            id=uuid.uuid4(),
            name="test",
            config={},
            model_versions={
                "rex": {
                    "conversation": "anthropic/claude-haiku-4.5",
                    "building": "anthropic/claude-sonnet-4.6",
                },
            },
        )
        assert "rex" in sim.model_versions


class TestEvalRunModelVersions:
    def test_eval_run_has_model_versions(self):
        run = EvalRun(
            id=uuid.uuid4(),
            simulation_id=uuid.uuid4(),
            eval_suite="full",
            status="completed",
            started_at=datetime.now(UTC),
            model_versions={
                "vera": {
                    "conversation": "anthropic/claude-haiku-4.5",
                    "building": "anthropic/claude-sonnet-4.6",
                },
            },
        )
        assert run.model_versions["vera"]["conversation"] == "anthropic/claude-haiku-4.5"

    def test_eval_run_detail_has_model_versions(self):
        detail = EvalRunDetail(
            id=uuid.uuid4(),
            simulation_id=uuid.uuid4(),
            eval_suite="full",
            status="completed",
            started_at=datetime.now(UTC),
            model_versions={
                "fork": {
                    "conversation": "deepseek/deepseek-v3.2",
                    "building": "deepseek/deepseek-v3.2",
                },
            },
        )
        assert detail.model_versions["fork"]["conversation"] == "deepseek/deepseek-v3.2"


class TestLLMClientFallbackTracking:
    def test_record_and_get_fallbacks(self):
        client = OpenRouterClient.__new__(OpenRouterClient)
        client._model_fallbacks = []
        client.record_fallback(
            agent_id="vera",
            requested_model="claude-sonnet-4-6",
            actual_model="claude-haiku-4-5",
            reason="model unavailable",
        )
        fallbacks = client.get_fallbacks()
        assert len(fallbacks) == 1
        assert fallbacks[0]["agent_id"] == "vera"
        assert fallbacks[0]["requested"] == "claude-sonnet-4-6"
        assert fallbacks[0]["actual"] == "claude-haiku-4-5"

    def test_get_fallbacks_empty(self):
        client = OpenRouterClient.__new__(OpenRouterClient)
        client._model_fallbacks = []
        assert client.get_fallbacks() == []

    def test_get_fallbacks_returns_copy(self):
        client = OpenRouterClient.__new__(OpenRouterClient)
        client._model_fallbacks = []
        client.record_fallback("vera", "a", "b", "test")
        fb = client.get_fallbacks()
        fb.clear()
        assert len(client.get_fallbacks()) == 1


class TestModelRegistry:
    def test_all_agents_have_resolvable_models(self):
        """Verify that the character sheet models all exist in MODEL_REGISTRY."""
        agent_models = [
            "claude-haiku-4-5", "claude-sonnet-4-6",
            "gemini-flash", "gemini-2.5-pro",
            "gpt-4o-mini", "gpt-5.2",
            "deepseek-v3.2",
            "grok-3-mini", "grok-3",
        ]
        for model in agent_models:
            assert model in MODEL_REGISTRY, f"{model} not in MODEL_REGISTRY"
            assert MODEL_REGISTRY[model].openrouter_id, f"{model} has no openrouter_id"

    def test_model_name_aliases_resolve(self):
        """All aliases should resolve to canonical names in MODEL_REGISTRY."""
        for alias, canonical in MODEL_NAME_ALIASES.items():
            assert canonical in MODEL_REGISTRY, f"Alias {alias} -> {canonical} not in registry"
