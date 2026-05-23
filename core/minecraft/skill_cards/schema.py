"""Typed skill-card models for text-only Minecraft command eval prompts."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from core.minecraft.commands.schema import CommandSchema, CommandSchemaSet

_SKILL_CARD_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_COMMAND_TOKEN_RE = re.compile(r"^![A-Za-z][A-Za-z0-9_]*$")
_SAFETY_CARD_ID = "safety"


@dataclass(frozen=True, slots=True)
class SkillCard:
    """Prompt guidance for one Minecraft action skill surface."""

    id: str
    title: str
    summary: str
    allowed_commands: tuple[str, ...] = ()
    disallowed_commands: tuple[str, ...] = ()
    guidance: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _SKILL_CARD_ID_RE.fullmatch(self.id):
            msg = f"skill card id must be stable kebab-case: {self.id!r}"
            raise ValueError(msg)

        allowed_commands = tuple(self.allowed_commands)
        disallowed_commands = tuple(self.disallowed_commands)
        for command_name in (*allowed_commands, *disallowed_commands):
            if not _COMMAND_TOKEN_RE.fullmatch(command_name):
                msg = f"skill card command must be a !name token: {command_name!r}"
                raise ValueError(msg)

        object.__setattr__(self, "allowed_commands", allowed_commands)
        object.__setattr__(self, "disallowed_commands", disallowed_commands)
        object.__setattr__(self, "guidance", tuple(self.guidance))
        object.__setattr__(self, "examples", tuple(self.examples))
        object.__setattr__(self, "tags", tuple(self.tags))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "allowed_commands": list(self.allowed_commands),
            "disallowed_commands": list(self.disallowed_commands),
            "guidance": list(self.guidance),
            "examples": list(self.examples),
            "tags": list(self.tags),
        }

    def with_allowed_commands(self, available_commands: Iterable[str]) -> SkillCard:
        """Return a copy trimmed to command tokens available in a scenario."""

        available = frozenset(available_commands)
        return replace(
            self,
            allowed_commands=tuple(
                command_name for command_name in self.allowed_commands if command_name in available
            ),
        )

    def render_prompt(
        self,
        commands: Mapping[str, CommandSchema] | CommandSchemaSet,
    ) -> str:
        """Render a deterministic prompt block using schemas for available commands."""

        command_map = command_schema_map(commands)
        lines = [
            f"## Skill Card: {self.id}",
            f"Title: {self.title}",
            f"Summary: {self.summary}",
        ]

        command_lines = [
            _format_command_line(command_name, command_map[command_name])
            for command_name in self.allowed_commands
            if command_name in command_map
        ]
        if command_lines:
            lines.extend(("", "Allowed commands:", *command_lines))

        if self.disallowed_commands:
            lines.extend(
                (
                    "",
                    "Disallowed commands:",
                    *(f"- {command_name}" for command_name in self.disallowed_commands),
                )
            )

        if self.guidance:
            lines.extend(("", "Guidance:", *(f"- {item}" for item in self.guidance)))

        example_lines = [
            f"- {example}"
            for example in self.examples
            if _example_is_renderable(example, command_map)
        ]
        if example_lines:
            lines.extend(("", "Examples:", *example_lines))

        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class SkillCardSet:
    """A deterministic collection of skill cards."""

    cards: tuple[SkillCard, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "cards", tuple(self.cards))

    def to_dict(self) -> dict[str, Any]:
        return {"cards": [card.to_dict() for card in self.cards]}

    def select(
        self,
        *,
        tags: Iterable[str] | None = None,
        ids: Iterable[str] | None = None,
        available_commands: CommandSchemaSet
        | Mapping[str, CommandSchema]
        | Iterable[str]
        | None = None,
    ) -> SkillCardSet:
        """Filter cards by scenario tags, explicit ids, and available tool surface."""

        tag_filter = frozenset(tags or ())
        id_filter = frozenset(ids or ())
        available_command_names = command_names(available_commands)

        selected: list[SkillCard] = []
        for card in self.cards:
            if id_filter and card.id not in id_filter:
                continue
            if tag_filter and tag_filter.isdisjoint(card.tags):
                continue

            selected_card = card
            if available_command_names is not None:
                selected_card = card.with_allowed_commands(available_command_names)
                if selected_card.id != _SAFETY_CARD_ID and not selected_card.allowed_commands:
                    continue

            selected.append(selected_card)

        return SkillCardSet(cards=tuple(selected))

    def render_prompt(
        self,
        commands: Mapping[str, CommandSchema] | CommandSchemaSet,
    ) -> str:
        return "\n\n".join(card.render_prompt(commands) for card in self.cards)


def command_schema_map(
    commands: Mapping[str, CommandSchema] | CommandSchemaSet,
) -> dict[str, CommandSchema]:
    """Build a lookup map keyed by command names and aliases."""

    if isinstance(commands, CommandSchemaSet):
        schemas = commands.commands
        command_map: dict[str, CommandSchema] = {}
    else:
        command_map = dict(commands)
        schemas = tuple(command_map.values())

    for schema in schemas:
        command_map.setdefault(schema.name, schema)
        for alias in schema.aliases:
            command_map.setdefault(alias, schema)
    return command_map


def command_names(
    commands: CommandSchemaSet | Mapping[str, CommandSchema] | Iterable[str] | None,
) -> frozenset[str] | None:
    """Return available command tokens, including aliases where schemas are supplied."""

    if commands is None:
        return None
    if isinstance(commands, CommandSchemaSet):
        return frozenset(command_schema_map(commands))
    if isinstance(commands, Mapping):
        return frozenset(command_schema_map(commands))
    if isinstance(commands, str):
        return frozenset((commands,))
    return frozenset(commands)


def _format_command_line(command_name: str, schema: CommandSchema) -> str:
    signature = _format_signature(command_name, schema)
    description = f" - {schema.description}" if schema.description else ""
    return f"- {signature}{description}"


def _format_signature(command_name: str, schema: CommandSchema) -> str:
    params = ", ".join(_format_param(param) for param in schema.params)
    return f"{command_name}({params})"


def _format_param(param: Any) -> str:
    suffix = "?" if param.optional else ""
    return f"{param.name}{suffix}: {param.type}"


def _example_is_renderable(
    example: str,
    command_map: Mapping[str, CommandSchema],
) -> bool:
    text = example.strip()
    if not text.startswith("!"):
        return True
    command_name = text.split(maxsplit=1)[0]
    return command_name in command_map
