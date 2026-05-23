"""Tests for the text-only Minecraft command response parser."""

from __future__ import annotations

from core.minecraft.eval import parse_model_response


def test_parse_empty_content() -> None:
    parsed = parse_model_response(" \n\t ")

    assert parsed.kind == "empty"
    assert parsed.parse_error == "empty"


def test_parse_chat_prefix_case_insensitive() -> None:
    parsed = parse_model_response("CHAT: I should not use that command.")

    assert parsed.kind == "chat"
    assert parsed.chat_text == "I should not use that command."
    assert parsed.parse_error is None


def test_parse_strips_leading_whitespace_and_code_fence() -> None:
    parsed = parse_model_response(
        """
        ```minecraft
        !observe
        ```
        """
    )

    assert parsed.kind == "command"
    assert parsed.raw == "!observe"
    assert parsed.command_token == "!observe"
    assert parsed.args == ()


def test_parse_command_with_no_args() -> None:
    parsed = parse_model_response("!inventory")

    assert parsed.kind == "command"
    assert parsed.command_token == "!inventory"
    assert parsed.args == ()


def test_parse_command_with_quoted_string_arg() -> None:
    parsed = parse_model_response('!say "hello nearby agent"')

    assert parsed.kind == "command"
    assert parsed.command_token == "!say"
    assert parsed.args == ("hello nearby agent",)


def test_parse_rejects_non_leading_command() -> None:
    parsed = parse_model_response("hello !move")

    assert parsed.kind == "empty"
    assert parsed.parse_error == "no-leading-command"


def test_parse_rejects_malformed_command_token() -> None:
    parsed = parse_model_response("!!move 1")

    assert parsed.kind == "empty"
    assert parsed.parse_error == "malformed-token"


def test_parse_rejects_multiple_commands() -> None:
    parsed = parse_model_response("!observe\n!move 1")

    assert parsed.kind == "empty"
    assert parsed.parse_error == "multiple-commands"


def test_parse_rejects_multiple_commands_on_one_line() -> None:
    parsed = parse_model_response("!observe !move")

    assert parsed.kind == "empty"
    assert parsed.parse_error == "multiple-commands"
