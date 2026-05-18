#!/usr/bin/env python3
"""Generate a Mindcraft profile JSON from ``agents/<id>/config.yaml`` (E3-4, #536).

Single source of truth: each agent's model assignment lives **only** in
``agents/<id>/config.yaml`` (``model_conversation`` / ``model_building``) and is
mirrored in the CLAUDE.md table. This generator turns those tiers into a
Mindcraft profile so the routing never gets hand-copied.

The emitted schema is exactly ``{"name", "model", "code_model"}`` — the same
minimal shape as the committed sibling templates
(``scripts/minecraft/profiles/stock-bot.json`` / ``routing-bot-a.json``):

* ``model``      ← conversation tier (Mindcraft's chat model)
* ``code_model`` ← building tier      (Mindcraft's ``!newAction`` / code model)

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
  ``model == code_model`` — expected and correct. Alpha's *non-verbal /
  no-chat-initiation* behavior is a Mindcraft settings/runtime concern owned by
  **E7-1** ("Alpha spawns ... emits no chat"), not a field of the profile
  schema at the pinned fork commit — see this issue's final notes.

Out of scope (E8): launching all agents. This only emits one profile per call.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / "agents"

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
) -> dict[str, str]:
    """Build the Mindcraft profile dict for one agent.

    Returns exactly ``{"name", "model", "code_model"}``.

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

    return {
        "name": _bot_name(agent_id),
        "model": model,
        "code_model": code_model,
    }


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
        help="Agent id, e.g. 'vera' (must match an agents/<id>/ directory).",
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
        help="Output path; '-' or omitted writes the JSON to stdout.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
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
