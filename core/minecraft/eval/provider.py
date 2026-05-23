"""Provider configuration for the text-only Minecraft command eval CLI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.llm_client import LOCAL_LLM_BASE_URL, OPENROUTER_BASE_URL, OpenRouterClient
from core.models import CostEventCreate

LOCAL_PROVIDER_ALIASES: dict[str, str] = {
    "local": "lmstudio",
    "lm-studio": "lmstudio",
    "lm_studio": "lmstudio",
    "lmstudio": "lmstudio",
    "openai-compatible": "openai-compatible",
    "openai_compatible": "openai-compatible",
}

TRUTHY_VALUES = frozenset(("1", "true", "yes", "on"))


class ProviderConfigError(ValueError):
    """Raised when provider configuration is incomplete or inconsistent."""


class ClientFactory(Protocol):
    def __call__(self, config: ProviderConfig) -> Any:
        """Create an async chat-completion client for the resolved provider."""


class NullCostRepo:
    """In-memory cost sink used by eval CLI clients so DB setup is not required."""

    def __init__(self) -> None:
        self.events: list[CostEventCreate] = []

    async def add_cost(self, event: CostEventCreate) -> None:
        self.events.append(event)


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Resolved provider settings safe for CLI metadata and client construction."""

    provider: str
    model: str
    base_url: str
    api_key_present: bool
    timeout: float = 30.0
    max_tokens: int = 256
    temperature: float = 0.2
    local_model: str | None = None
    local_model_building: str | None = None
    passthrough_model: bool = False
    _api_key: str | None = field(default=None, repr=False, compare=False)

    def create_client(self) -> OpenRouterClient:
        """Build an OpenRouterClient without requiring the app service bootstrap."""

        if self.provider == "openrouter":
            return OpenRouterClient(
                api_key=self._api_key,
                cost_repo=NullCostRepo(),
                provider="openrouter",
                base_url=self.base_url,
            )

        return OpenRouterClient(
            api_key=self._api_key,
            cost_repo=NullCostRepo(),
            provider=self.provider,
            base_url=self.base_url,
            local_model=self.local_model,
            local_model_building=self.local_model_building,
            passthrough_model=self.passthrough_model,
        )

    def public_metadata(self) -> dict[str, Any]:
        """Return metadata suitable for stdout, JSON, and artifact output."""

        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "key_present": self.api_key_present,
            "timeout": self.timeout,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }


def resolve_provider_config(
    argv_args: Any,
    env: Mapping[str, str],
) -> ProviderConfig:
    """Resolve provider config from CLI args over environment defaults.

    CLI flags take precedence over environment values. Local providers follow the
    same conventions as the local simulation tooling: ``LOCAL_LLM_*`` wins over
    legacy ``LLM_*`` names, and LM Studio gets its non-secret default API key.
    """

    provider = _normalize_provider(
        _first_text(_arg(argv_args, "provider"), env.get("LLM_PROVIDER"))
    )
    timeout = _positive_float(_arg(argv_args, "timeout"), default=30.0, field_name="timeout")
    max_tokens = _positive_int(
        _arg(argv_args, "max_tokens"),
        default=256,
        field_name="max_tokens",
    )
    temperature = _temperature(_arg(argv_args, "temperature"), default=0.2)

    if provider == "openrouter":
        return _resolve_openrouter(
            argv_args,
            env,
            timeout=timeout,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    return _resolve_local(
        argv_args,
        env,
        provider=provider,
        timeout=timeout,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def _resolve_openrouter(
    argv_args: Any,
    env: Mapping[str, str],
    *,
    timeout: float,
    max_tokens: int,
    temperature: float,
) -> ProviderConfig:
    api_key = _first_text(_arg(argv_args, "api_key"), env.get("OPENROUTER_API_KEY"))
    model = _clean_text(_arg(argv_args, "model"))
    base_url = _first_text(_arg(argv_args, "base_url"), env.get("OPENROUTER_BASE_URL"))
    if not base_url:
        base_url = OPENROUTER_BASE_URL

    if not api_key:
        raise ProviderConfigError("OPENROUTER_API_KEY is required for --provider openrouter")
    if not model:
        raise ProviderConfigError("--model is required for --provider openrouter")

    return ProviderConfig(
        provider="openrouter",
        model=model,
        base_url=base_url.rstrip("/"),
        api_key_present=True,
        timeout=timeout,
        max_tokens=max_tokens,
        temperature=temperature,
        _api_key=api_key,
    )


def _resolve_local(
    argv_args: Any,
    env: Mapping[str, str],
    *,
    provider: str,
    timeout: float,
    max_tokens: int,
    temperature: float,
) -> ProviderConfig:
    base_url = _first_text(
        _arg(argv_args, "base_url"),
        env.get("LOCAL_LLM_BASE_URL"),
        env.get("LLM_BASE_URL"),
    )
    if not base_url:
        base_url = LOCAL_LLM_BASE_URL

    api_key = _first_text(
        _arg(argv_args, "api_key"),
        env.get("LOCAL_LLM_API_KEY"),
        env.get("LLM_API_KEY"),
    )
    if api_key is None:
        api_key = "lm-studio"

    local_model = _first_text(_arg(argv_args, "model"), env.get("LOCAL_LLM_MODEL"))
    local_model_building = _clean_text(env.get("LOCAL_LLM_MODEL_BUILDING"))
    passthrough_model = _truthy(env.get("LOCAL_LLM_PASSTHROUGH_MODEL"))
    if not local_model:
        if _arg(argv_args, "dry_run") is True:
            local_model = "dry-run-local-model"
        else:
            raise ProviderConfigError(
                "LOCAL_LLM_MODEL or --model is required for local provider command evals"
            )

    return ProviderConfig(
        provider=provider,
        model=local_model,
        base_url=base_url.rstrip("/"),
        api_key_present=bool(api_key),
        timeout=timeout,
        max_tokens=max_tokens,
        temperature=temperature,
        local_model=local_model,
        local_model_building=local_model_building,
        passthrough_model=passthrough_model,
        _api_key=api_key,
    )


def _arg(argv_args: Any, name: str) -> Any:
    return getattr(argv_args, name, None)


def _normalize_provider(value: str | None) -> str:
    provider = (value or "lmstudio").strip().lower()
    if provider == "openrouter":
        return provider
    if provider in LOCAL_PROVIDER_ALIASES:
        return LOCAL_PROVIDER_ALIASES[provider]
    raise ProviderConfigError(
        f"Unknown provider {provider!r}. Use openrouter, lmstudio, or openai-compatible."
    )


def _first_text(*values: Any) -> str | None:
    for value in values:
        cleaned = _clean_text(value)
        if cleaned is not None:
            return cleaned
    return None


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _positive_float(value: Any, *, default: float, field_name: str) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ProviderConfigError(f"{field_name} must be a positive number") from exc
    if parsed <= 0:
        raise ProviderConfigError(f"{field_name} must be a positive number")
    return parsed


def _positive_int(value: Any, *, default: int, field_name: str) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ProviderConfigError(f"{field_name} must be a positive integer") from exc
    if parsed <= 0:
        raise ProviderConfigError(f"{field_name} must be a positive integer")
    return parsed


def _temperature(value: Any, *, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ProviderConfigError("temperature must be between 0 and 2") from exc
    if parsed < 0 or parsed > 2:
        raise ProviderConfigError("temperature must be between 0 and 2")
    return parsed


def _truthy(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() in TRUTHY_VALUES
