"""Tests for the E17 Minecraft action skill-card registry."""

from __future__ import annotations

import json
import re

from core.minecraft.commands import (
    DEFAULT_DISALLOWED_COMMANDS,
    CommandParam,
    CommandSchema,
    CommandSchemaSet,
)
from core.minecraft.skill_cards import (
    BUILTIN_SKILL_CARDS,
    SkillCard,
    SkillCardSet,
    get_default_registry,
    select_cards_for,
)

REQUIRED_CARD_IDS = [
    "move",
    "observe",
    "build",
    "craft",
    "gather",
    "conversation",
    "safety",
]


def _schema(
    name: str,
    *,
    params: tuple[CommandParam, ...] = (),
    aliases: tuple[str, ...] = (),
    description: str | None = None,
) -> CommandSchema:
    return CommandSchema(
        name=name,
        aliases=aliases,
        description=description or f"{name} fixture command.",
        params=params,
        source="fixture",
    )


def test_builtin_registry_has_stable_required_ids() -> None:
    ids = [card.id for card in BUILTIN_SKILL_CARDS]

    assert ids == REQUIRED_CARD_IDS
    assert all(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", card_id) for card_id in ids)


def test_builtin_registry_ids_are_unique_and_to_dict_round_trips_deterministically() -> None:
    registry = get_default_registry()
    ids = [card.id for card in registry.cards]

    assert len(ids) == len(set(ids))

    first = registry.to_dict()
    second = get_default_registry().to_dict()
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second,
        sort_keys=True,
        separators=(",", ":"),
    )

    restored = SkillCardSet(cards=tuple(SkillCard(**card_data) for card_data in first["cards"]))
    assert restored.to_dict() == first


def test_select_cards_for_filters_allowed_commands_and_keeps_safety() -> None:
    schema_set = CommandSchemaSet(
        commands=(
            _schema("!move"),
            _schema("!observe"),
            _schema("!craftRecipe"),
            _schema("!startConversation"),
        ),
        disallowed=DEFAULT_DISALLOWED_COMMANDS,
    )

    selected = select_cards_for(schema_set)
    cards_by_id = {card.id: card for card in selected.cards}

    assert [card.id for card in selected.cards] == [
        "move",
        "observe",
        "craft",
        "conversation",
        "safety",
    ]
    assert cards_by_id["move"].allowed_commands == ("!move",)
    assert cards_by_id["observe"].allowed_commands == ("!observe",)
    assert cards_by_id["craft"].allowed_commands == ("!craftRecipe",)
    assert cards_by_id["conversation"].allowed_commands == ("!startConversation",)
    assert cards_by_id["safety"].allowed_commands == ()


def test_select_supports_tag_and_id_filters() -> None:
    registry = get_default_registry()

    assert [card.id for card in registry.select(tags=("inventory",)).cards] == [
        "craft",
        "gather",
    ]
    assert [card.id for card in registry.select(ids=("conversation", "safety")).cards] == [
        "conversation",
        "safety",
    ]


def test_render_prompt_includes_resolved_signatures_guidance_and_examples() -> None:
    move_schema = _schema(
        "!move",
        params=(
            CommandParam(name="action_id", type="string"),
            CommandParam(name="direction", type="string"),
            CommandParam(name="distance_blocks", type="float"),
            CommandParam(name="timeout_ms", type="int", optional=True),
        ),
        description="Move a verified number of blocks.",
    )
    schema_set = CommandSchemaSet(commands=(move_schema,))
    [move_card] = select_cards_for(schema_set, ids=("move",)).cards

    prompt = move_card.render_prompt(schema_set)

    assert "## Skill Card: move" in prompt
    assert "Title: Move" in prompt
    assert "Allowed commands:" in prompt
    assert (
        "- !move(action_id: string, direction: string, distance_blocks: float, "
        "timeout_ms?: int) - Move a verified number of blocks."
    ) in prompt
    assert "Prefer short, verifiable moves" in prompt
    assert "!move action-move-001 north 3 10000" in prompt
    assert "!navigate" not in prompt
    assert "{{" not in prompt
    assert "}}" not in prompt
    assert "<" not in prompt
    assert ">" not in prompt


def test_safety_card_surfaces_default_disallowed_commands_verbatim() -> None:
    [safety_card] = get_default_registry().select(ids=("safety",)).cards

    assert safety_card.disallowed_commands == DEFAULT_DISALLOWED_COMMANDS

    prompt = safety_card.render_prompt(CommandSchemaSet())
    disallowed_lines = tuple(
        line.removeprefix("- ") for line in prompt.splitlines() if line.startswith("- !")
    )
    assert disallowed_lines == DEFAULT_DISALLOWED_COMMANDS
    assert "chat-only" in prompt
