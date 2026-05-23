"""Static extractor for Mindcraft-style JavaScript command definitions."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator
from pathlib import Path

from core.minecraft.commands.schema import CommandParam, CommandSchema, CommandSchemaSet

DEFAULT_DISALLOWED_COMMANDS: tuple[str, ...] = (
    "!exit",
    "!kill",
    "!quit",
    "!restart",
    "!shutdown",
    "!stop",
)
DEFAULT_INTERNAL_PREFIXES: tuple[str, ...] = ("_", "internal")

_EXPORT_COMMAND_RE = re.compile(r"\bexport\s+(?:const\s+[$A-Za-z_][$\w]*\s*=\s*|default\s*)\{")
_IDENTIFIER_RE = re.compile(r"[$A-Za-z_][$\w]*")


def extract_commands(
    paths: Iterable[Path],
    *,
    disallowed: Iterable[str] = (),
    internal_prefixes: Iterable[str] = (),
    source_label: str | None = None,
    skip_internal: bool = False,
) -> list[CommandSchema]:
    """Extract command schemas from JavaScript files or directories.

    The extractor is intentionally static: it reads committed command definition
    objects and never imports or executes Mindcraft code.
    """

    deny_list = frozenset(disallowed)
    internal_prefix_list = tuple(internal_prefixes)
    schemas: list[CommandSchema] = []

    for js_file in _iter_js_files(paths):
        text = js_file.read_text(encoding="utf-8")
        for object_text in _exported_object_literals(text):
            schema = _schema_from_object(
                object_text,
                source=source_label or js_file.as_posix(),
                disallowed=deny_list,
                internal_prefixes=internal_prefix_list,
            )
            if schema is None:
                continue
            if skip_internal and schema.internal:
                continue
            schemas.append(schema)

    return sorted(schemas, key=lambda command: (command.name, command.source, command.aliases))


def extract_from_default_locations(repo_root: Path) -> CommandSchemaSet:
    """Extract from the committed fork overlay plus an optional Mindcraft clone.

    ``MINDCRAFT_DIR`` follows ``scripts/minecraft/setup-mindcraft.sh``: relative
    paths are resolved from ``repo_root`` and default to ``./mindcraft``.
    """

    fork_commands = repo_root / "scripts" / "minecraft" / "fork-src" / "agent" / "commands"
    mindcraft_root = _mindcraft_root(repo_root)
    upstream_commands = mindcraft_root / "src" / "agent" / "commands"

    commands: list[CommandSchema] = []
    if upstream_commands.is_dir():
        commands.extend(
            extract_commands(
                [upstream_commands],
                disallowed=DEFAULT_DISALLOWED_COMMANDS,
                internal_prefixes=DEFAULT_INTERNAL_PREFIXES,
                source_label="mindcraft",
            )
        )
    if fork_commands.is_dir():
        commands.extend(
            extract_commands(
                [fork_commands],
                disallowed=DEFAULT_DISALLOWED_COMMANDS,
                internal_prefixes=DEFAULT_INTERNAL_PREFIXES,
                source_label="fork",
            )
        )

    return CommandSchemaSet(commands=tuple(commands), disallowed=DEFAULT_DISALLOWED_COMMANDS)


def _mindcraft_root(repo_root: Path) -> Path:
    configured = os.environ.get("MINDCRAFT_DIR", "./mindcraft")
    path = Path(configured)
    if path.is_absolute():
        return path
    return repo_root / path


def _iter_js_files(paths: Iterable[Path]) -> Iterator[Path]:
    files: list[Path] = []
    for path in paths:
        candidate = Path(path)
        if candidate.is_file() and candidate.suffix == ".js":
            files.append(candidate)
        elif candidate.is_dir():
            files.extend(candidate.rglob("*.js"))
    yield from sorted(files, key=lambda item: item.as_posix())


def _exported_object_literals(text: str) -> Iterator[str]:
    for match in _EXPORT_COMMAND_RE.finditer(text):
        open_brace = match.end() - 1
        close_brace = _find_matching_brace(text, open_brace)
        if close_brace is not None:
            yield text[open_brace : close_brace + 1]


def _schema_from_object(
    object_text: str,
    *,
    source: str,
    disallowed: frozenset[str],
    internal_prefixes: tuple[str, ...],
) -> CommandSchema | None:
    properties = dict(_iter_object_properties(object_text))
    name = _read_string_expression(properties.get("name", ""))
    if not name:
        return None

    aliases = tuple(_read_string_array(properties.get("aliases", "")))
    params = tuple(_read_params(properties.get("params", "")))
    command_names = (name, *aliases)
    return CommandSchema(
        name=name,
        aliases=aliases,
        description=_read_string_expression(properties.get("description", "")),
        params=params,
        source=source,
        disallowed=any(command_name in disallowed for command_name in command_names),
        internal=any(
            _matches_internal_prefix(command_name, internal_prefixes)
            for command_name in command_names
        ),
    )


def _read_params(value: str) -> Iterator[CommandParam]:
    text = value.strip()
    if not text.startswith("{"):
        return

    for param_name, param_value in _iter_object_properties(text):
        param_properties = dict(_iter_object_properties(param_value))
        yield CommandParam(
            name=param_name,
            type=_read_string_expression(param_properties.get("type", "")) or "string",
            optional=_read_bool(param_properties.get("optional", "")),
            description=_read_string_expression(param_properties.get("description", "")),
        )


def _iter_object_properties(object_text: str) -> Iterator[tuple[str, str]]:
    text = object_text.strip()
    if not text.startswith("{"):
        return

    index = 1
    end = len(text) - 1 if text.endswith("}") else len(text)
    while index < end:
        index = _skip_whitespace_and_comments(text, index)
        if index >= end:
            break
        if text[index] == ",":
            index += 1
            continue

        key, key_end = _read_property_key(text, index)
        if not key:
            index += 1
            continue

        colon = _skip_whitespace_and_comments(text, key_end)
        if colon >= end or text[colon] != ":":
            index = key_end
            continue

        value_start = _skip_whitespace_and_comments(text, colon + 1)
        value_end = _find_property_value_end(text, value_start, end)
        yield key, text[value_start:value_end].strip()
        index = value_end + 1


def _read_property_key(text: str, index: int) -> tuple[str, int]:
    if index >= len(text):
        return "", index
    if text[index] in ("'", '"'):
        value, end = _read_static_string(text, index)
        return value or "", end
    match = _IDENTIFIER_RE.match(text, index)
    if not match:
        return "", index
    return match.group(0), match.end()


def _find_property_value_end(text: str, start: int, end: int) -> int:
    index = start
    curly_depth = 0
    square_depth = 0
    paren_depth = 0
    while index < end:
        skipped = _skip_string_or_comment(text, index)
        if skipped != index:
            index = skipped
            continue

        char = text[index]
        if char == "{":
            curly_depth += 1
        elif char == "}":
            if curly_depth == 0 and square_depth == 0 and paren_depth == 0:
                return index
            curly_depth = max(0, curly_depth - 1)
        elif char == "[":
            square_depth += 1
        elif char == "]":
            square_depth = max(0, square_depth - 1)
        elif char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth = max(0, paren_depth - 1)
        elif char == "," and curly_depth == 0 and square_depth == 0 and paren_depth == 0:
            return index
        index += 1
    return end


def _find_matching_brace(text: str, open_brace: int) -> int | None:
    depth = 0
    index = open_brace
    while index < len(text):
        skipped = _skip_string_or_comment(text, index)
        if skipped != index:
            index = skipped
            continue

        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _read_string_expression(value: str) -> str:
    text = value.strip()
    parts: list[str] = []
    index = 0

    while index < len(text):
        index = _skip_whitespace_and_comments(text, index)
        if index >= len(text) or text[index] not in ("'", '"', "`"):
            break

        part, end = _read_static_string(text, index)
        if part is None:
            break
        parts.append(part)
        index = _skip_whitespace_and_comments(text, end)
        if index >= len(text) or text[index] != "+":
            break
        index += 1

    return "".join(parts)


def _read_string_array(value: str) -> list[str]:
    text = value.strip()
    if not text.startswith("["):
        return []

    aliases: list[str] = []
    index = 1
    while index < len(text):
        index = _skip_whitespace_and_comments(text, index)
        if index >= len(text) or text[index] == "]":
            break
        if text[index] == ",":
            index += 1
            continue
        if text[index] in ("'", '"', "`"):
            alias, end = _read_static_string(text, index)
            if alias:
                aliases.append(alias)
            index = end
            continue
        index += 1
    return aliases


def _read_static_string(text: str, start: int) -> tuple[str | None, int]:
    quote = text[start]
    if quote not in ("'", '"', "`"):
        return None, start

    chars: list[str] = []
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            if index + 1 >= len(text):
                return None, index + 1
            chars.append(_decode_escape(text[index + 1]))
            index += 2
            continue
        if char == quote:
            return "".join(chars), index + 1
        chars.append(char)
        index += 1
    return None, index


def _decode_escape(char: str) -> str:
    return {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "b": "\b",
        "f": "\f",
        "v": "\v",
    }.get(char, char)


def _read_bool(value: str) -> bool:
    return bool(re.match(r"^\s*true\b", value))


def _matches_internal_prefix(name: str, prefixes: tuple[str, ...]) -> bool:
    normalized = name[1:] if name.startswith("!") else name
    return any(
        name.startswith(prefix) or normalized.startswith(prefix.lstrip("!")) for prefix in prefixes
    )


def _skip_whitespace_and_comments(text: str, index: int) -> int:
    current = index
    while current < len(text):
        while current < len(text) and text[current].isspace():
            current += 1
        skipped = _skip_comment(text, current)
        if skipped == current:
            return current
        current = skipped
    return current


def _skip_string_or_comment(text: str, index: int) -> int:
    if index >= len(text):
        return index
    if text[index] in ("'", '"', "`"):
        _, end = _read_static_string(text, index)
        return end
    return _skip_comment(text, index)


def _skip_comment(text: str, index: int) -> int:
    if text.startswith("//", index):
        newline = text.find("\n", index + 2)
        return len(text) if newline == -1 else newline + 1
    if text.startswith("/*", index):
        close = text.find("*/", index + 2)
        return len(text) if close == -1 else close + 2
    return index
