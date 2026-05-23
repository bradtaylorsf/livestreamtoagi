"""Parser for text-only Minecraft command eval model responses."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any, Literal

from core.minecraft.scenarios.schema import COMMAND_TOKEN_RE

ParsedKind = Literal["command", "chat", "empty"]


@dataclass(frozen=True, slots=True)
class ParsedResponse:
    """Normalized model response shape consumed by the semantic evaluator."""

    kind: ParsedKind
    raw: str
    command_token: str | None = None
    args: tuple[str, ...] = ()
    chat_text: str | None = None
    parse_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "raw": self.raw,
            "command_token": self.command_token,
            "args": list(self.args),
            "chat_text": self.chat_text,
            "parse_error": self.parse_error,
        }


def parse_model_response(content: str) -> ParsedResponse:
    """Parse one model response into a command, chat-only response, or error."""

    raw = _strip_code_fence(content.strip())
    if not raw:
        return ParsedResponse(kind="empty", raw=raw, parse_error="empty")

    if raw.casefold().startswith("chat:"):
        return ParsedResponse(
            kind="chat",
            raw=raw,
            chat_text=raw.split(":", 1)[1].strip(),
        )

    command_lines = _leading_command_lines(raw)
    if len(command_lines) > 1:
        return ParsedResponse(
            kind="empty",
            raw=raw,
            parse_error="multiple-commands",
        )

    first_line = raw.splitlines()[0].strip()
    if not first_line:
        return ParsedResponse(kind="empty", raw=raw, parse_error="empty")

    first_token = first_line.split(maxsplit=1)[0]
    if not first_token.startswith("!"):
        return ParsedResponse(kind="empty", raw=raw, parse_error="no-leading-command")
    if not COMMAND_TOKEN_RE.fullmatch(first_token):
        return ParsedResponse(kind="empty", raw=raw, parse_error="malformed-token")

    try:
        tokens = shlex.split(first_line)
    except ValueError:
        return ParsedResponse(
            kind="empty",
            raw=raw,
            parse_error="malformed-token",
        )
    if not tokens:
        return ParsedResponse(kind="empty", raw=raw, parse_error="empty")
    if not COMMAND_TOKEN_RE.fullmatch(tokens[0]):
        return ParsedResponse(kind="empty", raw=raw, parse_error="malformed-token")
    if any(COMMAND_TOKEN_RE.fullmatch(token) for token in tokens[1:]):
        return ParsedResponse(kind="empty", raw=raw, parse_error="multiple-commands")

    return ParsedResponse(kind="command", raw=raw, command_token=tokens[0], args=tuple(tokens[1:]))


def _strip_code_fence(content: str) -> str:
    if not content.startswith("```"):
        return content

    lines = content.splitlines()
    if len(lines) < 2 or not lines[-1].strip().startswith("```"):
        return content
    return "\n".join(lines[1:-1]).strip()


def _leading_command_lines(content: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in content.splitlines() if line.strip().startswith("!"))
