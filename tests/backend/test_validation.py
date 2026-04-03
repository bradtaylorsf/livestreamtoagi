"""Tests for memory system input validation."""

from __future__ import annotations

import pytest

from core.memory.validation import InvalidAgentIdError, validate_agent_id


class TestValidateAgentId:
    """Tests for agent_id format validation."""

    def test_valid_simple_id(self) -> None:
        assert validate_agent_id("rex") == "rex"

    def test_valid_with_underscore(self) -> None:
        assert validate_agent_id("agent_one") == "agent_one"

    def test_valid_with_hyphen(self) -> None:
        assert validate_agent_id("agent-one") == "agent-one"

    def test_valid_mixed_case(self) -> None:
        assert validate_agent_id("Rex") == "Rex"

    def test_valid_alphanumeric(self) -> None:
        assert validate_agent_id("agent1") == "agent1"

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(InvalidAgentIdError):
            validate_agent_id("")

    def test_rejects_starts_with_number(self) -> None:
        with pytest.raises(InvalidAgentIdError):
            validate_agent_id("1agent")

    def test_rejects_special_characters(self) -> None:
        with pytest.raises(InvalidAgentIdError):
            validate_agent_id("agent@name")

    def test_rejects_spaces(self) -> None:
        with pytest.raises(InvalidAgentIdError):
            validate_agent_id("agent name")

    def test_rejects_sql_injection_attempt(self) -> None:
        with pytest.raises(InvalidAgentIdError):
            validate_agent_id("'; DROP TABLE agents; --")

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(InvalidAgentIdError):
            validate_agent_id("../../etc/passwd")

    def test_rejects_too_long(self) -> None:
        with pytest.raises(InvalidAgentIdError):
            validate_agent_id("a" * 51)

    def test_accepts_max_length(self) -> None:
        agent_id = "a" * 50
        assert validate_agent_id(agent_id) == agent_id

    def test_rejects_non_string(self) -> None:
        with pytest.raises(InvalidAgentIdError):
            validate_agent_id(123)  # type: ignore[arg-type]

    def test_rejects_none(self) -> None:
        with pytest.raises(InvalidAgentIdError):
            validate_agent_id(None)  # type: ignore[arg-type]

    def test_is_value_error_subclass(self) -> None:
        """InvalidAgentIdError should be catchable as ValueError."""
        with pytest.raises(ValueError):
            validate_agent_id("")
