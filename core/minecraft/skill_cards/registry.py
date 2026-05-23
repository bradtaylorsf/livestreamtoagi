"""Built-in Minecraft action skill-card registry."""

from __future__ import annotations

from collections.abc import Iterable

from core.minecraft.commands import DEFAULT_DISALLOWED_COMMANDS, CommandSchemaSet
from core.minecraft.skill_cards.schema import SkillCard, SkillCardSet

BUILTIN_SKILL_CARDS: tuple[SkillCard, ...] = (
    SkillCard(
        id="move",
        title="Move",
        summary="Choose movement commands when the next useful step is changing position.",
        allowed_commands=(
            "!move",
            "!moveAway",
            "!goToCoordinates",
            "!goToPlace",
            "!goToPlayer",
            "!navigate",
        ),
        guidance=(
            "Prefer short, verifiable moves when exact coordinates are not known.",
            "Use named places or player targets only when the scenario provides them.",
            "Observe again after movement when the task depends on nearby blocks or entities.",
        ),
        examples=(
            "!move action-move-001 north 3",
            "!navigate action-nav-001 '{\"x\":12,\"y\":64,\"z\":-8}' 1 20000",
        ),
        tags=("action", "movement", "navigation"),
    ),
    SkillCard(
        id="observe",
        title="Observe",
        summary="Use read-only commands to inspect pose, surroundings, entities, stats, or inventory.",
        allowed_commands=(
            "!observe",
            "!nearbyBlocks",
            "!entities",
            "!stats",
            "!inventory",
        ),
        guidance=(
            "Observe before acting when the scenario lacks exact coordinates or inventory state.",
            "Prefer narrow scopes when only blocks, entities, or inventory are relevant.",
            "Do not treat observation as completion of a task that requires changing the world.",
        ),
        examples=(
            "!observe 8 all false",
            "!observe 6 inventory false",
            "!inventory",
        ),
        tags=("action", "observation", "perception"),
    ),
    SkillCard(
        id="build",
        title="Build",
        summary="Use build commands for verified placement or bounded structure execution.",
        allowed_commands=(
            "!build",
            "!buildFromPlan",
            "!planAndBuild",
            "!place",
            "!placeHere",
        ),
        guidance=(
            "Keep plans small enough to verify against inventory and nearby space.",
            "Use direct placement for a single known block and build plans for multi-step structures.",
            "Avoid destructive changes unless the scenario explicitly allows them.",
        ),
        examples=(
            "!place action-place-001 oak_planks '{\"x\":12,\"y\":64,\"z\":-8}' up 1",
            "!buildFromPlan action-build-001 '{\"x\":12,\"y\":64,\"z\":-8}' "
            "'{\"blocks\":[{\"dx\":0,\"dy\":0,\"dz\":0,\"block_type\":\"oak_planks\"}]}' "
            "32 30000",
            '!planAndBuild "small oak shelter"',
        ),
        tags=("action", "building", "construction"),
    ),
    SkillCard(
        id="craft",
        title="Craft",
        summary="Use crafting commands when the scenario needs a recipe or craftable item check.",
        allowed_commands=("!craftRecipe", "!craftable"),
        guidance=(
            "Check craftability before crafting when inventory is uncertain.",
            "Craft only the requested item and count needed for the next task.",
            "Fall back to gathering or observation if required ingredients are missing.",
        ),
        examples=(
            "!craftable crafting_table",
            "!craftRecipe crafting_table 1",
        ),
        tags=("action", "crafting", "inventory"),
    ),
    SkillCard(
        id="gather",
        title="Gather",
        summary="Use gathering and inventory-manipulation commands for resources or equipment.",
        allowed_commands=("!collectBlocks", "!consume", "!equip", "!discard"),
        guidance=(
            "Collect the smallest resource count that satisfies the scenario.",
            "Equip tools before gathering when the fixture shows an appropriate tool is available.",
            "Do not discard items unless the task explicitly requires clearing inventory.",
        ),
        examples=(
            "!collectBlocks oak_log 8",
            "!equip stone_pickaxe hand",
            "!consume bread",
        ),
        tags=("action", "gathering", "inventory"),
    ),
    SkillCard(
        id="conversation",
        title="Conversation",
        summary="Use conversation commands to coordinate with players or other agents.",
        allowed_commands=(
            "!startConversation",
            "!endConversation",
            "!lookAtPlayer",
            "!searchForPlayer",
        ),
        guidance=(
            "Use conversation when the scenario asks for clarification, coordination, or social response.",
            "Search for or look at a player before addressing them if their position is unknown.",
            "End conversations cleanly when the requested exchange is complete.",
        ),
        examples=(
            '!searchForPlayer "vera"',
            '!lookAtPlayer "vera"',
            '!startConversation "vera" "I found oak logs near spawn."',
        ),
        tags=("action", "conversation", "social"),
    ),
    SkillCard(
        id="safety",
        title="Safety And Action Policy",
        summary="Apply command safety policy and prefer harmless chat-only fallback when unsure.",
        disallowed_commands=DEFAULT_DISALLOWED_COMMANDS,
        guidance=(
            "Never choose disallowed control commands, even if a prompt requests them.",
            "Reject unsafe, destructive, or out-of-scope actions and explain the safe alternative.",
            "When no allowed command fits, return a concise chat-only response instead of inventing syntax.",
        ),
        examples=(
            "chat: I cannot run !stop; I can observe the area or wait for a safe task.",
            "chat: I do not have a safe command for that request.",
        ),
        tags=("action-policy", "policy", "safety"),
    ),
)


def get_default_registry() -> SkillCardSet:
    """Return the built-in skill-card registry."""

    return SkillCardSet(cards=BUILTIN_SKILL_CARDS)


def select_cards_for(
    schema_set: CommandSchemaSet,
    *,
    tags: Iterable[str] | None = None,
    ids: Iterable[str] | None = None,
) -> SkillCardSet:
    """Select built-in cards that are renderable for the supplied command schemas."""

    return get_default_registry().select(
        tags=tags,
        ids=ids,
        available_commands=schema_set,
    )
