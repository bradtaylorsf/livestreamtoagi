"""Custom exception hierarchy for the agent system.

Provides distinct exception types so callers can differentiate between
transient (retryable) errors, fatal (non-retryable) errors, and
validation failures instead of catching bare ``Exception``.
"""


class AgentError(Exception):
    """Base exception for all agent-related errors."""


class AgentCostCapExceeded(AgentError):  # noqa: N818 - issue contract names this exception
    """Raised when an agent is blocked by the hourly spend cap."""

    def __init__(self, agent_id: str, spend: object, cap: object) -> None:
        self.agent_id = agent_id
        self.spend = spend
        self.cap = cap
        super().__init__(
            f"Agent {agent_id!r} hourly spend cap exceeded: spend=${spend}, cap=${cap}"
        )


class TransientError(AgentError):
    """Retryable error — network timeouts, rate limits, temporary DB failures."""


class FatalError(AgentError):
    """Non-retryable error — bad config, missing required data."""


class ValidationError(AgentError):
    """Bad input or invalid state."""
