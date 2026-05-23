"""Text-only Minecraft command eval runner."""

from __future__ import annotations

from core.minecraft.eval.dataset_replay import (
    DatasetLoadError,
    PassingPrompt,
    build_command_text,
    filter_prompts,
    load_passing_prompts,
    prompt_to_case_id,
)
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
from core.minecraft.eval.live_runner import (
    BridgeClient,
    CaseGenerator,
    CommandCase,
    FakeBridgeClient,
    resolve_command_name,
    run_live_command_smoke,
    supported_command_inputs,
)
from core.minecraft.eval.live_telemetry import (
    ActionEvent,
    CaseResult,
    LiveRunSummary,
    OutcomeClass,
    classify_bridge_status,
)
from core.minecraft.eval.parser import ParsedResponse, parse_model_response
from core.minecraft.eval.provider import (
    ProviderConfig,
    ProviderConfigError,
    resolve_provider_config,
)
from core.minecraft.eval.replay_cli import run_dataset_replay
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
    "ActionEvent",
    "BridgeClient",
    "CaseGenerator",
    "CaseResult",
    "CommandCase",
    "DatasetLoadError",
    "EvalOutcome",
    "EvalProfile",
    "EvalProfileError",
    "EvalReport",
    "FakeBridgeClient",
    "BUILTIN_PROFILES",
    "DEFAULT_PROFILE_NAME",
    "LiveRunSummary",
    "OutcomeClass",
    "ParsedResponse",
    "ProviderConfig",
    "ProviderConfigError",
    "PassingPrompt",
    "RunSummary",
    "ScoredRun",
    "ScoredScenario",
    "ScenarioRunResult",
    "build_command_text",
    "build_scenario_messages",
    "classify_bridge_status",
    "comparison_md_text",
    "evaluate_response",
    "filter_prompts",
    "list_profiles",
    "load_passing_prompts",
    "parse_model_response",
    "parse_world_config",
    "prompt_to_case_id",
    "resolve_command_name",
    "report_md_text",
    "resolve_profile",
    "resolve_provider_config",
    "run_eval",
    "run_dataset_replay",
    "run_live_command_smoke",
    "score_run",
    "scored_run_from_scores_json",
    "scores_json_dict",
    "supported_command_inputs",
    "write_comparison_md",
    "write_generations_ndjson",
    "write_passing_prompts_ndjson",
    "write_report_md",
    "write_scores_json",
]
