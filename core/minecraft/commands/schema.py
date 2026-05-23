"""Typed command schema models for Minecraft command evals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CommandParam:
    """A single command parameter definition."""

    name: str
    type: str  # noqa: A003 - mirrors the JavaScript command schema field.
    optional: bool = False
    description: str = ""

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "name": self.name,
            "type": self.type,
            "optional": self.optional,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class CommandSchema:
    """A command definition consumable by the text-only Minecraft eval harness."""

    name: str
    aliases: tuple[str, ...] = ()
    description: str = ""
    params: tuple[CommandParam, ...] = ()
    required_param_names: tuple[str, ...] = field(default_factory=tuple)
    optional_param_names: tuple[str, ...] = field(default_factory=tuple)
    source: str = ""
    disallowed: bool = False
    internal: bool = False

    def __post_init__(self) -> None:
        params = tuple(self.params)
        aliases = tuple(self.aliases)
        required = tuple(self.required_param_names) or tuple(
            param.name for param in params if not param.optional
        )
        optional = tuple(self.optional_param_names) or tuple(
            param.name for param in params if param.optional
        )

        object.__setattr__(self, "params", params)
        object.__setattr__(self, "aliases", aliases)
        object.__setattr__(self, "required_param_names", required)
        object.__setattr__(self, "optional_param_names", optional)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "description": self.description,
            "params": {
                param.name: {
                    "type": param.type,
                    "optional": param.optional,
                    "description": param.description,
                }
                for param in self.params
            },
            "required": list(self.required_param_names),
            "optional": list(self.optional_param_names),
            "source": self.source,
            "disallowed": self.disallowed,
            "internal": self.internal,
        }


@dataclass(frozen=True, slots=True)
class CommandSchemaSet:
    """A deterministic collection of extracted command schemas."""

    commands: tuple[CommandSchema, ...] = ()
    disallowed: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "commands", tuple(self.commands))
        object.__setattr__(self, "disallowed", tuple(sorted(set(self.disallowed))))

    def to_dict(self) -> dict[str, Any]:
        commands = sorted(
            self.commands,
            key=lambda command: (command.name, command.source, command.aliases),
        )
        return {
            "commands": [command.to_dict() for command in commands],
            "disallowed": list(self.disallowed),
        }
