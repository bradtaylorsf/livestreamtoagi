"""Text-only Minecraft command eval runner."""

from __future__ import annotations

from core.minecraft.eval.evaluator import EvalOutcome, EvalReport, evaluate_response
from core.minecraft.eval.live_profile import (
    BUILTIN_PROFILES,
    DEFAULT_PROFILE_NAME,
    EvalProfile,
    EvalProfileError,
    list_profiles,
    parse_world_config,
    resolve_profile,
)
from core.minecraft.eval.parser import ParsedResponse, parse_model_response
from core.minecraft.eval.provider import (
    ProviderConfig,
    ProviderConfigError,
    resolve_provider_config,
)
from core.minecraft.eval.report import (
    ScoredRun,
    ScoredScenario,
    comparison_md_text,
    report_md_text,
    score_run,
    scored_run_from_scores_json,
    scores_json_dict,
    write_comparison_md,
    write_generations_ndjson,
    write_passing_prompts_ndjson,
    write_report_md,
    write_scores_json,
)
from core.minecraft.eval.runner import (
    RunSummary,
    ScenarioRunResult,
    build_scenario_messages,
    run_eval,
)

__all__ = [
    "EvalOutcome",
    "EvalProfile",
    "EvalProfileError",
    "EvalReport",
    "BUILTIN_PROFILES",
    "DEFAULT_PROFILE_NAME",
    "ParsedResponse",
    "ProviderConfig",
    "ProviderConfigError",
    "RunSummary",
    "ScoredRun",
    "ScoredScenario",
    "ScenarioRunResult",
    "build_scenario_messages",
    "comparison_md_text",
    "evaluate_response",
    "list_profiles",
    "parse_model_response",
    "parse_world_config",
    "report_md_text",
    "resolve_profile",
    "resolve_provider_config",
    "run_eval",
    "score_run",
    "scored_run_from_scores_json",
    "scores_json_dict",
    "write_comparison_md",
    "write_generations_ndjson",
    "write_passing_prompts_ndjson",
    "write_report_md",
    "write_scores_json",
]
