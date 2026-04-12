"""Custom exception hierarchy for the agent system.

Provides distinct exception types so callers can differentiate between
transient (retryable) errors, fatal (non-retryable) errors, and
validation failures instead of catching bare ``Exception``.
"""


class AgentError(Exception):
    """Base exception for all agent-related errors."""


class TransientError(AgentError):
    """Retryable error — network timeouts, rate limits, temporary DB failures."""


class FatalError(AgentError):
    """Non-retryable error — bad config, missing required data."""


class ValidationError(AgentError):
    """Bad input or invalid state."""
