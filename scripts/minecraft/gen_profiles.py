#!/usr/bin/env python3
"""Generate Mindcraft profile JSON from ``agents/<id>/config.yaml`` (E3-4 / E8-1).

Single source of truth: each agent's model assignment lives **only** in
``agents/<id>/config.yaml`` (``model_conversation`` / ``model_building``) and is
mirrored in the CLAUDE.md table. This generator turns those tiers into a
Mindcraft profile so the routing never gets hand-copied.

The emitted schema keeps ``{"name", "model", "code_model"}`` as the required
Mindcraft routing keys and adds E8 conversation metadata:
``{"bot_responder", "personality"}``.

* ``model``      ← conversation tier (Mindcraft's chat model)
* ``code_model`` ← building tier      (Mindcraft's ``!newAction`` / code model)
* ``bot_responder`` ← Mindcraft's respond/ignore prompt override
* ``personality``   ← numeric thresholds the fork conversation layer can read

Two provider forms (E1 inputs on #536):

* ``openrouter`` (default — production reference form):
  ``openrouter/<config value>``. Each raw config value is validated through
  ``core.llm_client.MODEL_NAME_ALIASES`` into ``MODEL_REGISTRY`` — the same
  drift guard ``tests/backend/test_mc_model_routing.py`` uses — so a profile
  can never silently diverge from ``core/llm_client.py``.
* ``lmstudio`` (mandated local-dev / LM Studio validation path, decision 0003):
  ``lmstudio/<local model id>`` from ``--local-chat`` / ``--local-code``
  (falling back to ``LOCAL_LLM_MODEL`` / ``LOCAL_LLM_MODEL_BUILDING``). Never
  emits ``openrouter/`` and skips the registry check — zero external spend.

Policy bindings (E1 inputs on #536, cross-checked against the pivot plan):

* **Management is refused.** Management is a content *filter*, never a world
  bot (E7-5: "Management is a filter, never a bot"); no profile is generated.
* **Alpha is generated.** Alpha is the first vertical-slice agent (E7-1). Its
  config sets both tiers to the same model, so its profile has
  ``model == code_model`` — expected and correct. Alpha's profile now also pins
  ``respond_probability == initiate_probability == 0`` so the E8
  conversation layer treats it as action-only.

E8-1 extends the E3-4 single-agent generator with batch output for every
conversational agent. Launching those agents remains out of scope here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / "agents"
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
BOOTSTRAP_ENV = "LTAG_GEN_PROFILES_BOOTSTRAPPED"


def _load_yaml_module() -> Any:
    """Import PyYAML, re-execing through the repo venv when needed.

    Live verification can invoke this script directly via ``/usr/bin/env
    python3``. On machines where that interpreter lacks repo dependencies, the
    old top-level ``import yaml`` failed before argument parsing. Re-execing
    once through ``.venv/bin/python`` keeps direct script execution compatible
    with the repo's PATH-safe command convention.
    """
    try:
        import yaml as yaml_module

        return yaml_module
    except ModuleNotFoundError as exc:
        if exc.name != "yaml":
            raise
        if VENV_PYTHON.is_file() and os.environ.get(BOOTSTRAP_ENV) != "1":
            os.environ[BOOTSTRAP_ENV] = "1"
            os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])
        raise ModuleNotFoundError(
            "PyYAML is required to read agents/<id>/config.yaml. "
            "Run this script with .venv/bin/python or install repo dependencies."
        ) from exc


yaml = _load_yaml_module()

# Make ``core`` importable when this file is run as a standalone script
# (mirrors scripts/check_local_llm.py); harmless/idempotent under importlib.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Agents that are deliberately never spawned as world bots, so no Mindcraft
# profile is generated for them. Management is a content filter applied
# out-of-band (E1 input on #536; E7-5: "Management is a filter, never a bot").
NON_BOT_AGENTS = frozenset({"management"})

# Not a real agent — a placeholder config with unresolvable ``{...}`` tokens.
PSEUDO_AGENTS = frozenset({"template"})

VALID_PROVIDERS = ("openrouter", "lmstudio")

PERSONALITY_PROFILE_KEYS = (
    "chattiness",
    "initiative",
    "interrupt_tendency",
    "eavesdrop_tendency",
    "closing_weight",
    "role_priority_bonus",
    "respond_probability",
    "initiate_probability",
    "interrupt_bias",
    "eavesdrop_probability",
    "adjacency",
)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    """Clamp a probability-like value into the inclusive ``[lower, upper]`` range."""
    return max(lower, min(upper, value))


def _float_knob(cfg: dict[str, Any], key: str, default: float = 0.0) -> float:
    """Read a numeric agent config knob with a stable default for optional fields."""
    return float(cfg.get(key, default) or 0.0)


def _adjacency_map(cfg: dict[str, Any]) -> dict[str, float]:
    """Return the raw adjacency map as JSON-safe ``str -> float`` values."""
    raw = cfg.get("adjacency") or {}
    if not isinstance(raw, dict):
        raise ValueError("agent config field 'adjacency' must be a mapping when present")
    return {str(agent_id): float(weight) for agent_id, weight in raw.items()}


def _bot_responder_prompt(personality: dict[str, Any]) -> str:
    """Build the Mindcraft ``bot_responder`` prompt from the mapped knobs."""
    if personality["respond_probability"] == 0:
        return (
            "Decide whether this action-only bot should answer a bot-to-bot "
            "message. Return exactly one word: ignore. This profile does not "
            "participate in normal conversation."
        )

    return (
        "Decide whether this bot should answer a bot-to-bot message. Return "
        "exactly one word: respond or ignore.\n"
        f"Chattiness is {personality['chattiness']:.2f}; target respond rate is "
        f"{personality['respond_probability']:.3f}. Lean toward respond in "
        "rough proportion to that target when the message is addressed to this "
        "bot, advances its current goal, or fits the nearby conversation.\n"
        f"Interrupt tendency is {personality['interrupt_tendency']:.2f}. Only "
        "override a busy/current-action state when that tendency is high and "
        "the new message is urgent or directly blocks the current task; "
        "otherwise return ignore until free."
    )


def build_personality(cfg: dict[str, Any]) -> dict[str, Any]:
    """Map agent config knobs onto Mindcraft conversation metadata.

    Decision 0004 says Mindcraft's native decentralized hook is the
    ``bot_responder`` prompt, while numeric chattiness/initiative/eavesdrop/
    adjacency behavior needs our fork layer. This function is pure so tests can
    prove the acceptance criterion without launching Minecraft or an LLM.
    """
    chattiness = _float_knob(cfg, "chattiness")
    initiative = _float_knob(cfg, "initiative")
    interrupt_tendency = _float_knob(cfg, "interrupt_tendency")
    eavesdrop_tendency = _float_knob(cfg, "eavesdrop_tendency")
    closing_weight = _float_knob(cfg, "closing_weight")
    role_priority_bonus = _float_knob(cfg, "role_priority_bonus")

    if cfg.get("id") == "alpha":
        respond_probability = 0.0
        initiate_probability = 0.0
    else:
        respond_probability = _clamp(
            0.15 + 0.7 * chattiness + 0.15 * interrupt_tendency
        )
        initiate_probability = _clamp(
            0.05 + 0.7 * chattiness * (0.5 + 0.5 * initiative)
        )

    personality: dict[str, Any] = {
        "chattiness": chattiness,
        "initiative": initiative,
        "interrupt_tendency": interrupt_tendency,
        "eavesdrop_tendency": eavesdrop_tendency,
        "closing_weight": closing_weight,
        "role_priority_bonus": role_priority_bonus,
        "respond_probability": respond_probability,
        "initiate_probability": initiate_probability,
        "interrupt_bias": interrupt_tendency,
        "eavesdrop_probability": eavesdrop_tendency,
        "adjacency": _adjacency_map(cfg),
    }
    personality["bot_responder"] = _bot_responder_prompt(personality)
    return personality


def _bot_name(agent_id: str) -> str:
    """Agent id → single-word PascalCase Minecraft username.

    ``vera`` → ``Vera`` (matches the committed StockBot/RoutingBotA
    single-word-username convention). Any ``-``/``_`` separators collapse so
    the result is always a legal Minecraft name.
    """
    parts = agent_id.replace("-", "_").split("_")
    return "".join(part.capitalize() for part in parts if part)


def load_agent_config(agent_id: str, agents_dir: Path = AGENTS_DIR) -> dict[str, Any]:
    """Read ``agents/<agent_id>/config.yaml`` and return it as a dict.

    Raises ``FileNotFoundError`` with an actionable message if the agent
    directory or its ``config.yaml`` does not exist.
    """
    agent_dir = agents_dir / agent_id
    config_path = agent_dir / "config.yaml"
    if not agent_dir.is_dir():
        raise FileNotFoundError(
            f"No agent directory {agent_dir} — known agents: "
            f"{', '.join(sorted(p.name for p in agents_dir.iterdir() if p.is_dir()))}"
        )
    if not config_path.is_file():
        raise FileNotFoundError(f"Missing {config_path}")
    data = yaml.safe_load(config_path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{config_path} did not parse to a mapping")
    return data


def discover_agent_ids(agents_dir: Path = AGENTS_DIR) -> list[str]:
    """Return real conversational agent ids discovered from ``agents/*/config.yaml``.

    ``template`` is skipped because it is a placeholder config, and
    ``management`` is skipped because it is an out-of-band content filter, not a
    Mindcraft world bot.
    """
    ids: list[str] = []
    for config_path in agents_dir.glob("*/config.yaml"):
        agent_id = config_path.parent.name
        if agent_id in PSEUDO_AGENTS or agent_id in NON_BOT_AGENTS:
            continue
        ids.append(agent_id)
    return sorted(ids)


def _assert_resolves_into_registry(raw_model_id: str) -> None:
    """Fail if a raw config model id does not alias into ``MODEL_REGISTRY``.

    Mirrors ``tests/backend/test_mc_model_routing._resolve_canonical``: the
    profile must never drift from ``core/llm_client.py``.
    """
    from core.llm_client import MODEL_NAME_ALIASES, MODEL_REGISTRY

    canonical = MODEL_NAME_ALIASES.get(raw_model_id, raw_model_id)
    if canonical not in MODEL_REGISTRY:
        raise ValueError(
            f"{raw_model_id!r} does not resolve into "
            f"core.llm_client.MODEL_REGISTRY via MODEL_NAME_ALIASES "
            f"(got {canonical!r}) — agents/<id>/config.yaml drifted from "
            f"core/llm_client.py"
        )


def build_profile(
    agent_id: str,
    *,
    provider: str = "openrouter",
    local_chat: str | None = None,
    local_code: str | None = None,
    agents_dir: Path = AGENTS_DIR,
) -> dict[str, Any]:
    """Build the Mindcraft profile dict for one agent.

    Returns ``{"name", "model", "code_model", "bot_responder", "personality"}``.
    The first three keys are the required Mindcraft routing surface; the added
    keys drive E8 decentralized conversation behavior.

    * ``provider="openrouter"`` — ``openrouter/<config value>`` for each tier,
      validated through ``core.llm_client`` (raises on registry drift).
    * ``provider="lmstudio"`` — ``lmstudio/<id>`` from ``local_chat`` /
      ``local_code`` (env fallback ``LOCAL_LLM_MODEL`` /
      ``LOCAL_LLM_MODEL_BUILDING``; code tier falls back to the chat id).
      Never emits ``openrouter/``; skips the registry check.

    Raises ``ValueError`` for Management (refused — it is a filter, never a
    bot) or an unknown provider.
    """
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"Unknown provider {provider!r}; use one of {VALID_PROVIDERS}")
    if agent_id in NON_BOT_AGENTS:
        raise ValueError(
            f"Refusing to generate a Mindcraft profile for {agent_id!r}: "
            f"it is a content filter applied out-of-band, never a world bot "
            f"(E1 input on #536; E7-5)."
        )

    # Always validate the agent exists (and is real) regardless of provider —
    # gives a clear error before we emit anything.
    cfg = load_agent_config(agent_id, agents_dir=agents_dir)

    if provider == "lmstudio":
        chat = local_chat or os.environ.get("LOCAL_LLM_MODEL")
        if not chat:
            raise ValueError(
                "lmstudio provider needs a chat model id: pass --local-chat "
                "or set LOCAL_LLM_MODEL (a served LM Studio model id)."
            )
        code = local_code or os.environ.get("LOCAL_LLM_MODEL_BUILDING") or chat
        model = f"lmstudio/{chat}"
        code_model = f"lmstudio/{code}"
    else:  # openrouter
        conv = cfg["model_conversation"]
        build = cfg["model_building"]
        _assert_resolves_into_registry(conv)
        _assert_resolves_into_registry(build)
        model = f"openrouter/{conv}"
        code_model = f"openrouter/{build}"

    personality_with_prompt = build_personality(cfg)
    bot_responder = str(personality_with_prompt["bot_responder"])
    personality = {
        key: personality_with_prompt[key] for key in PERSONALITY_PROFILE_KEYS
    }

    return {
        "name": _bot_name(agent_id),
        "model": model,
        "code_model": code_model,
        "bot_responder": bot_responder,
        "personality": personality,
    }


def build_all_profiles(
    provider: str = "openrouter",
    local_chat: str | None = None,
    local_code: str | None = None,
    agents_dir: Path = AGENTS_DIR,
) -> dict[str, dict[str, Any]]:
    """Build profiles for every discovered conversational agent."""
    profiles: dict[str, dict[str, Any]] = {}
    for agent_id in discover_agent_ids(agents_dir=agents_dir):
        try:
            profiles[agent_id] = build_profile(
                agent_id,
                provider=provider,
                local_chat=local_chat,
                local_code=local_code,
                agents_dir=agents_dir,
            )
        except ValueError as exc:
            raise ValueError(f"Failed to build profile for {agent_id!r}: {exc}") from exc
    return profiles


def _profile_filename(agent_id: str) -> str:
    """Output filename for a generated per-agent profile."""
    return f"{agent_id.replace('_', '-')}-bot.json"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="gen_profiles.py",
        description=(
            "Generate a Mindcraft profile JSON from agents/<id>/config.yaml. "
            "Management is refused (it is a filter, never a bot)."
        ),
    )
    parser.add_argument(
        "agent_id",
        nargs="?",
        help="Agent id, e.g. 'vera' (must match an agents/<id>/ directory).",
    )
    parser.add_argument(
        "--all",
        dest="all_agents",
        action="store_true",
        help="Generate profiles for all conversational agents.",
    )
    parser.add_argument(
        "--provider",
        choices=VALID_PROVIDERS,
        default="openrouter",
        help="openrouter (default, production reference) or lmstudio (local).",
    )
    parser.add_argument(
        "--local-chat",
        default=None,
        help="lmstudio only: chat-tier model id (else $LOCAL_LLM_MODEL).",
    )
    parser.add_argument(
        "--local-code",
        default=None,
        help=(
            "lmstudio only: code-tier model id (else $LOCAL_LLM_MODEL_BUILDING, else the chat id)."
        ),
    )
    parser.add_argument(
        "--out",
        default="-",
        help=(
            "Output path; '-' or omitted writes JSON to stdout. "
            "With --all, non-stdout paths are profile directories."
        ),
    )
    args = parser.parse_args(argv)
    if args.all_agents and args.agent_id:
        parser.error("pass either an agent_id or --all, not both")
    if not args.all_agents and not args.agent_id:
        parser.error("pass an agent_id or --all")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.all_agents:
        try:
            profiles = build_all_profiles(
                provider=args.provider,
                local_chat=args.local_chat,
                local_code=args.local_code,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 1

        rendered = json.dumps(profiles, indent=4)
        if args.out in ("-", ""):
            print(rendered)
        else:
            out_dir = Path(args.out)
            out_dir.mkdir(parents=True, exist_ok=True)
            for agent_id, profile in profiles.items():
                profile_path = out_dir / _profile_filename(agent_id)
                profile_path.write_text(json.dumps(profile, indent=4) + "\n")
            print(f"✓ Wrote {len(profiles)} profiles to {out_dir}", file=sys.stderr)
        return 0

    try:
        profile = build_profile(
            args.agent_id,
            provider=args.provider,
            local_chat=args.local_chat,
            local_code=args.local_code,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(profile, indent=4)
    if args.out in ("-", ""):
        print(rendered)
    else:
        out_path = Path(args.out)
        out_path.write_text(rendered + "\n")
        print(f"✓ Wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
