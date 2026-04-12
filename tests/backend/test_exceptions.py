"""Tests for custom exception hierarchy (#354)."""

from core.exceptions import AgentError, FatalError, TransientError, ValidationError


def test_exception_hierarchy():
    """All custom exceptions inherit from AgentError."""
    assert issubclass(TransientError, AgentError)
    assert issubclass(FatalError, AgentError)
    assert issubclass(ValidationError, AgentError)
    assert issubclass(AgentError, Exception)


def test_transient_error_catchable_as_agent_error():
    """TransientError can be caught as AgentError."""
    try:
        raise TransientError("network timeout")
    except AgentError:
        pass  # Expected


def test_fatal_error_catchable_as_agent_error():
    """FatalError can be caught as AgentError."""
    try:
        raise FatalError("bad config")
    except AgentError:
        pass  # Expected


def test_validation_error_catchable_as_agent_error():
    """ValidationError can be caught as AgentError."""
    try:
        raise ValidationError("invalid input")
    except AgentError:
        pass  # Expected


def test_agent_error_not_caught_by_subclass():
    """AgentError should NOT be caught by TransientError."""
    caught = False
    try:
        raise AgentError("generic error")
    except TransientError:
        caught = True
    except AgentError:
        pass
    assert not caught


def test_llm_error_not_subclass_of_agent_error():
    """LLMError is a separate hierarchy — not an AgentError subclass."""
    from core.llm_client import LLMError

    assert not issubclass(LLMError, AgentError)


def test_llm_error_transient_flag():
    """LLMError.transient is True for retryable status codes."""
    from core.llm_client import LLMError

    err_429 = LLMError("rate limit", status_code=429)
    assert err_429.transient is True

    err_400 = LLMError("bad request", status_code=400)
    assert err_400.transient is False
