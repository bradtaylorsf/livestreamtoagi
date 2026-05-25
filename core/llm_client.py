"""Async OpenAI-compatible LLM client with cost tracking.

OpenRouter remains the default provider, but the same client can also target
local OpenAI-compatible servers such as LM Studio.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

import httpx

from core.exceptions import AgentCostCapExceeded
from core.model_config import AGENT_MODEL_DEFAULTS, agent_model_ref, resolve_model_reference
from core.models import CostEventCreate, LLMResponse, StreamChunk, ToolCall

if TYPE_CHECKING:
    import uuid
    from collections.abc import AsyncGenerator

    from core.cost_governor import CostGovernor
    from core.repos.cost_repo import CostRepo

logger = logging.getLogger(__name__)

current_agent_id: ContextVar[str | None] = ContextVar("current_agent_id", default=None)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
LOCAL_LLM_BASE_URL = "http://localhost:1234/v1"
LOCAL_LLM_DEFAULT_API_KEY = "lm-studio"

RETRYABLE_STATUS_CODES = {429, 500, 502, 503}
MAX_RETRIES = 3
BACKOFF_BASE = 1  # seconds
MAX_RETRY_AFTER = 60  # cap Retry-After header
LOCAL_PROVIDER_ALIASES = {
    "local": "lmstudio",
    "lm-studio": "lmstudio",
    "lm_studio": "lmstudio",
    "lmstudio": "lmstudio",
    "openai-compatible": "openai-compatible",
    "openai_compatible": "openai-compatible",
}
MODEL_NAME_ALIASES = {
    "anthropic/claude-haiku-4-5": "claude-haiku-4-5",
    "anthropic/claude-haiku-4.5": "claude-haiku-4-5",
    "anthropic/claude-sonnet-4-6": "claude-sonnet-4-6",
    "anthropic/claude-sonnet-4.6": "claude-sonnet-4-6",
    "google/gemini-flash": "gemini-flash",
    "google/gemini-2.5-pro": "gemini-2.5-pro",
    "openai/gpt-4o-mini": "gpt-4o-mini",
    "openai/gpt-5.2": "gpt-5.2",
    "deepseek/deepseek-v3.2": "deepseek-v3.2",
    "x-ai/grok-3-mini": "grok-3-mini",
    "x-ai/grok-3": "grok-3",
}
MODEL_NAME_ALIASES.update(
    {
        agent_model_ref(agent_id, tier): MODEL_NAME_ALIASES.get(model_id, model_id)
        for agent_id, tiers in AGENT_MODEL_DEFAULTS.items()
        for tier, model_id in tiers.items()
    }
)
OFFLINE_TEST_COST_USD = Decimal("0.0001")

# Canonical models that represent the "building" tier (heavier, JSON-capable).
# Used by local providers to route reflection/dream calls to a larger local model.
BUILDING_TIER_MODELS = frozenset(
    {
        "claude-sonnet-4-6",
        "gemini-2.5-pro",
        "gpt-5.2",
        "grok-3",
    }
)


@contextmanager
def agent_cost_context(agent_id: str | None) -> Iterator[None]:
    """Attribute nested LLM cost events to the current agent."""
    token = current_agent_id.set(agent_id)
    try:
        yield
    finally:
        current_agent_id.reset(token)


@dataclass
class ModelConfig:
    openrouter_id: str
    input_price_per_1m: Decimal
    output_price_per_1m: Decimal


# Fallback prices in USD per 1M tokens — used when OpenRouter API is unreachable.
# Updated 2026-04-07 from https://openrouter.ai/api/v1/models
MODEL_REGISTRY: dict[str, ModelConfig] = {
    "claude-haiku-4-5": ModelConfig(
        openrouter_id="anthropic/claude-haiku-4.5",
        input_price_per_1m=Decimal("1.00"),
        output_price_per_1m=Decimal("5.00"),
    ),
    "claude-sonnet-4-6": ModelConfig(
        openrouter_id="anthropic/claude-sonnet-4.6",
        input_price_per_1m=Decimal("3.00"),
        output_price_per_1m=Decimal("15.00"),
    ),
    "gemini-flash": ModelConfig(
        openrouter_id="google/gemini-2.5-flash",
        input_price_per_1m=Decimal("0.30"),
        output_price_per_1m=Decimal("2.50"),
    ),
    "gemini-2.5-pro": ModelConfig(
        openrouter_id="google/gemini-2.5-pro",
        input_price_per_1m=Decimal("1.25"),
        output_price_per_1m=Decimal("10.00"),
    ),
    "gpt-4o-mini": ModelConfig(
        openrouter_id="openai/gpt-4o-mini",
        input_price_per_1m=Decimal("0.15"),
        output_price_per_1m=Decimal("0.60"),
    ),
    "gpt-5.2": ModelConfig(
        openrouter_id="openai/gpt-5.2",
        input_price_per_1m=Decimal("1.75"),
        output_price_per_1m=Decimal("14.00"),
    ),
    "deepseek-v3.2": ModelConfig(
        openrouter_id="deepseek/deepseek-chat-v3-0324",
        input_price_per_1m=Decimal("0.20"),
        output_price_per_1m=Decimal("0.77"),
    ),
    "grok-3-mini": ModelConfig(
        openrouter_id="x-ai/grok-3-mini",
        input_price_per_1m=Decimal("0.30"),
        output_price_per_1m=Decimal("0.50"),
    ),
    "grok-3": ModelConfig(
        openrouter_id="x-ai/grok-3",
        input_price_per_1m=Decimal("3.00"),
        output_price_per_1m=Decimal("15.00"),
    ),
}

# Reverse lookup: openrouter_id -> canonical name
_OPENROUTER_ID_TO_CANONICAL: dict[str, str] = {
    cfg.openrouter_id: name for name, cfg in MODEL_REGISTRY.items()
}


def _normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized == "openrouter":
        return "openrouter"
    if normalized in LOCAL_PROVIDER_ALIASES:
        return LOCAL_PROVIDER_ALIASES[normalized]
    raise ValueError(
        f"Unknown LLM provider '{provider}'. Use 'openrouter', 'lmstudio', or 'openai-compatible'."
    )


async def refresh_pricing(
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, tuple[Decimal, Decimal]]:
    """Fetch live model pricing from OpenRouter and update MODEL_REGISTRY.

    Returns a dict of canonical_name -> (old_input, old_output) for models
    whose prices changed, so callers can log the diff.  Falls back silently
    to hardcoded prices on any error.
    """
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient()
    changes: dict[str, tuple[Decimal, Decimal]] = {}
    try:
        resp = await client.get(
            f"{OPENROUTER_BASE_URL}/models",
            timeout=10.0,
        )
        if resp.status_code != 200:
            logger.warning(
                "OpenRouter /models returned %d — using fallback prices",
                resp.status_code,
            )
            return changes

        data = resp.json()
        models_list = data.get("data", [])

        for model_data in models_list:
            model_id = model_data.get("id", "")
            canonical = _OPENROUTER_ID_TO_CANONICAL.get(model_id)
            if canonical is None:
                continue

            pricing = model_data.get("pricing", {})
            prompt_raw = pricing.get("prompt")
            completion_raw = pricing.get("completion")
            if prompt_raw is None or completion_raw is None:
                continue

            try:
                # OpenRouter returns price per token; convert to per 1M
                input_per_1m = Decimal(str(prompt_raw)) * Decimal("1000000")
                output_per_1m = Decimal(str(completion_raw)) * Decimal("1000000")
            except (InvalidOperation, TypeError):
                logger.warning(
                    "Bad pricing data for %s: prompt=%r completion=%r",
                    model_id,
                    prompt_raw,
                    completion_raw,
                )
                continue

            cfg = MODEL_REGISTRY[canonical]
            if cfg.input_price_per_1m != input_per_1m or cfg.output_price_per_1m != output_per_1m:
                changes[canonical] = (cfg.input_price_per_1m, cfg.output_price_per_1m)
                cfg.input_price_per_1m = input_per_1m
                cfg.output_price_per_1m = output_per_1m

        if changes:
            for name, (old_in, old_out) in changes.items():
                new = MODEL_REGISTRY[name]
                logger.info(
                    "Price updated %s: $%s/$%s -> $%s/$%s per 1M tokens",
                    name,
                    old_in,
                    old_out,
                    new.input_price_per_1m,
                    new.output_price_per_1m,
                )
        else:
            logger.info("All model prices match OpenRouter — no updates needed")

    except Exception:
        logger.warning("Failed to fetch OpenRouter pricing — using fallback prices", exc_info=True)
    finally:
        if owns_client:
            await client.aclose()

    return changes


class LLMError(Exception):
    """Raised when an LLM API call fails after retries."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.transient = status_code in RETRYABLE_STATUS_CODES


def estimate_cost(model_config: ModelConfig, input_tokens: int, output_tokens: int) -> Decimal:
    return (
        Decimal(input_tokens) * model_config.input_price_per_1m
        + Decimal(output_tokens) * model_config.output_price_per_1m
    ) / Decimal("1000000")


class OpenRouterClient:
    def __init__(
        self,
        api_key: str | None,
        cost_repo: CostRepo,
        langfuse_client: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
        *,
        provider: str = "openrouter",
        base_url: str | None = None,
        local_model: str | None = None,
        local_model_building: str | None = None,
        passthrough_model: bool = False,
        cost_governor: CostGovernor | None = None,
    ) -> None:
        self._provider = _normalize_provider(provider)
        if self._provider == "openrouter":
            if not isinstance(api_key, str) or not api_key.strip():
                raise ValueError("OPENROUTER_API_KEY must be a non-empty string")
            self._api_key = api_key.strip()
            self._base_url = (base_url or OPENROUTER_BASE_URL).rstrip("/")
        else:
            if api_key is not None and not isinstance(api_key, str):
                raise ValueError("api_key must be a string when using a local LLM provider")
            self._api_key = (api_key or LOCAL_LLM_DEFAULT_API_KEY).strip()
            self._base_url = (base_url or LOCAL_LLM_BASE_URL).rstrip("/")

        self._local_model = (
            local_model.strip() if isinstance(local_model, str) and local_model.strip() else None
        )
        self._local_model_building = (
            local_model_building.strip()
            if isinstance(local_model_building, str) and local_model_building.strip()
            else None
        )
        self._passthrough_model = passthrough_model
        self._cost_repo = cost_repo
        self._cost_governor = cost_governor
        self._langfuse = langfuse_client
        self._lost_cost_events: int = 0
        self._last_cost_failure_ts: float | None = None
        self._total_cost_calls: int = 0
        self._simulation_id: uuid.UUID | None = None  # Set externally for simulation tracking
        self._model_fallbacks: list[dict[str, str]] = []
        self._owns_client = http_client is None
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if self._provider == "openrouter":
            headers.update(
                {
                    "HTTP-Referer": "https://livestreamtoagi.com",
                    "X-Title": "Livestream AGI",
                }
            )
        self._client = http_client or httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def record_fallback(
        self,
        agent_id: str,
        requested_model: str,
        actual_model: str,
        reason: str,
    ) -> None:
        """Record when a model fallback occurs (e.g., requested model unavailable)."""
        entry = {
            "agent_id": agent_id,
            "requested": requested_model,
            "actual": actual_model,
            "reason": reason,
        }
        self._model_fallbacks.append(entry)
        logger.warning("Model fallback: %s", entry)

    def get_fallbacks(self) -> list[dict[str, str]]:
        """Return all model fallback events recorded during this session."""
        return list(self._model_fallbacks)

    @property
    def provider(self) -> str:
        """Configured provider name."""
        return self._provider

    @property
    def base_url(self) -> str:
        """Provider base URL."""
        return self._base_url

    @property
    def is_local_provider(self) -> bool:
        """True when requests go to a local/OpenAI-compatible provider."""
        return self._provider != "openrouter"

    def _resolve_model(self, model: str) -> ModelConfig:
        model = resolve_model_reference(model)
        canonical_model = MODEL_NAME_ALIASES.get(model, model)
        if canonical_model not in MODEL_REGISTRY:
            if self.is_local_provider:
                return ModelConfig(
                    openrouter_id=model,
                    input_price_per_1m=Decimal("0"),
                    output_price_per_1m=Decimal("0"),
                )
            raise ValueError(
                f"Unknown model '{model}'. Available: {', '.join(sorted(MODEL_REGISTRY))}"
            )
        return MODEL_REGISTRY[canonical_model]

    def runtime_model_id(self, model: str) -> str:
        """Return the model ID that will be sent to the provider."""
        model = resolve_model_reference(model)
        model_config = self._resolve_model(model)
        if self._provider == "openrouter":
            return model_config.openrouter_id
        if self._passthrough_model:
            return model
        canonical = MODEL_NAME_ALIASES.get(model, model)
        if self._local_model_building and canonical in BUILDING_TIER_MODELS:
            return self._local_model_building
        if self._local_model:
            return self._local_model
        return model

    def model_provenance(self, model: str) -> str:
        """Return a stable provider:model string for simulation provenance."""
        return f"{self._provider}:{self.runtime_model_id(model)}"

    def _estimate_call_cost(
        self, model_config: ModelConfig, input_tokens: int, output_tokens: int
    ) -> Decimal:
        if self.is_local_provider:
            return Decimal("0")
        return estimate_cost(model_config, input_tokens, output_tokens)

    async def _log_cost(
        self,
        agent_id: str | None,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: Decimal,
        latency_ms: int,
        stream: bool,
        openrouter_id: str | None,
        simulation_id: uuid.UUID | None = None,
        provider: str | None = None,
        runtime_model: str | None = None,
    ) -> None:
        """Log cost with 3 retries and exponential backoff."""
        self._total_cost_calls += 1

        if self._lost_cost_events > 0:
            logger.warning(
                "Cost data loss detected: %d events lost so far — logging may be unreliable",
                self._lost_cost_events,
            )

        details: dict[str, Any] = {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
            "stream": stream,
            "openrouter_id": openrouter_id,
        }
        if provider is not None:
            details["provider"] = provider
        if runtime_model is not None:
            details["runtime_model"] = runtime_model

        event = CostEventCreate(
            agent_id=agent_id,
            cost_type="llm_call",
            amount=cost,
            details=details,
            simulation_id=simulation_id,
        )
        max_attempts = 4  # 1 initial + 3 retries
        recorded = False
        for attempt in range(max_attempts):
            try:
                await self._cost_repo.add_cost(event)
                recorded = True
                break
            except Exception:
                if attempt < max_attempts - 1:
                    logger.debug(
                        "Cost event retry %d/%d failed for model=%s agent=%s",
                        attempt + 1,
                        max_attempts,
                        model,
                        agent_id,
                        exc_info=True,
                    )
                    await asyncio.sleep(0.5 * (2**attempt))
                else:
                    self._lost_cost_events += 1
                    self._last_cost_failure_ts = time.time()
                    logger.warning(
                        "Cost event lost (total lost: %d) for model=%s agent=%s",
                        self._lost_cost_events,
                        model,
                        agent_id,
                    )

        if recorded and self._cost_governor is not None and agent_id is not None:
            await self._cost_governor.record_and_check(agent_id, cost)

    async def _raise_if_agent_capped(self, agent_id: str | None) -> None:
        if self._cost_governor is None or agent_id is None:
            return
        allowed, spend, cap = await self._cost_governor.is_allowed(agent_id)
        if not allowed:
            raise AgentCostCapExceeded(agent_id, spend, cap)

    def diagnostics(self) -> dict[str, Any]:
        """Return cost tracking diagnostics."""
        return {
            "provider": self._provider,
            "base_url": self._base_url,
            "local_model": self._local_model,
            "lost_cost_events": self._lost_cost_events,
            "last_failure_ts": self._last_cost_failure_ts,
            "total_cost_calls": self._total_cost_calls,
            "loss_rate": (
                self._lost_cost_events / self._total_cost_calls
                if self._total_cost_calls > 0
                else 0.0
            ),
        }

    def _trace_langfuse(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        cost: Decimal,
    ) -> None:
        if self._langfuse is None:
            return
        try:
            self._langfuse.generation(
                model=model,
                usage={
                    "input": input_tokens,
                    "output": output_tokens,
                },
                metadata={
                    "latency_ms": latency_ms,
                    "estimated_cost": float(cost),
                },
            )
        except Exception:
            logger.exception("Langfuse trace failed for model=%s", model)

    async def _request_with_retry(
        self,
        payload: dict,
        timeout: float,
        stream: bool,
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                if stream:
                    req = self._client.build_request(
                        "POST", "/chat/completions", json=payload, timeout=timeout
                    )
                    resp = await self._client.send(req, stream=True)
                else:
                    resp = await self._client.post(
                        "/chat/completions", json=payload, timeout=timeout
                    )
                if resp.status_code not in RETRYABLE_STATUS_CODES:
                    return resp
                # Retryable error — close streaming response before retry
                if stream:
                    await resp.aclose()
                retry_after = min(
                    float(resp.headers.get("Retry-After", 0)),
                    MAX_RETRY_AFTER,
                )
                delay = max(retry_after, BACKOFF_BASE * (2**attempt))
                logger.warning(
                    "%s %d on attempt %d/%d, retrying in %.1fs",
                    self._provider,
                    resp.status_code,
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                last_exc = LLMError(f"HTTP {resp.status_code}", status_code=resp.status_code)
                await asyncio.sleep(delay)
            except (httpx.TimeoutException, httpx.ReadError) as exc:
                last_exc = exc
                if attempt < MAX_RETRIES - 1:
                    delay = BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        "%s %s on attempt %d/%d, retrying in %.1fs",
                        self._provider,
                        type(exc).__name__,
                        attempt + 1,
                        MAX_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)
        raise LLMError(
            f"All {MAX_RETRIES} retries exhausted: {last_exc}",
            status_code=getattr(last_exc, "status_code", None),
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        agent_id: str | None = None,
        *,
        timeout: float = 30.0,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        simulation_id: uuid.UUID | None = None,
    ) -> LLMResponse:
        effective_agent_id = agent_id if agent_id is not None else current_agent_id.get()
        requested_model = resolve_model_reference(model, agent_id=effective_agent_id)
        model_config = self._resolve_model(requested_model)
        runtime_model = self.runtime_model_id(requested_model)
        await self._raise_if_agent_capped(effective_agent_id)
        payload: dict[str, Any] = {
            "model": runtime_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            # LM Studio only accepts string tool_choice values (none/auto/required).
            # Downgrade dict-style forcing to "required"; engine fallback re-injects
            # the specific tool call if the model picks the wrong one.
            if self.is_local_provider and isinstance(tool_choice, dict):
                payload["tool_choice"] = "required"
            else:
                payload["tool_choice"] = tool_choice

        start = time.monotonic()
        resp = await self._request_with_retry(payload, timeout, stream=False)
        latency_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code != 200:
            body = resp.text[:500]
            logger.warning("%s error %d: %s", self._provider, resp.status_code, body)
            raise LLMError(
                f"{self._provider} returned {resp.status_code}: {body}",
                status_code=resp.status_code,
            )

        data = resp.json()
        choices = data.get("choices")
        if not choices:
            raise LLMError(f"{self._provider} returned no choices in response")

        message = choices[0]["message"]
        content = message.get("content") or ""

        # Parse tool calls if present
        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function", {})
            args_raw = fn.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                logger.warning(
                    "Malformed tool call JSON from LLM (tool=%s): %s",
                    fn.get("name", "?"),
                    args_raw[:200],
                )
                args = {"_raw": args_raw}
            tool_calls.append(
                ToolCall(
                    id=tc.get("id", ""),
                    name=fn.get("name", ""),
                    arguments=args,
                )
            )

        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        openrouter_id = data.get("id")
        cost = self._estimate_call_cost(model_config, input_tokens, output_tokens)

        await self._log_cost(
            effective_agent_id,
            requested_model,
            input_tokens,
            output_tokens,
            cost,
            latency_ms,
            stream=False,
            openrouter_id=openrouter_id,
            simulation_id=simulation_id or self._simulation_id,
            provider=self._provider,
            runtime_model=runtime_model,
        )
        trace_model = runtime_model if self.is_local_provider else requested_model
        self._trace_langfuse(trace_model, input_tokens, output_tokens, latency_ms, cost)

        return LLMResponse(
            content=content,
            model=requested_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=cost,
            latency_ms=latency_ms,
            openrouter_id=openrouter_id,
            tool_calls=tool_calls,
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        agent_id: str | None = None,
        *,
        timeout: float = 30.0,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        simulation_id: uuid.UUID | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        effective_agent_id = agent_id if agent_id is not None else current_agent_id.get()
        requested_model = resolve_model_reference(model, agent_id=effective_agent_id)
        model_config = self._resolve_model(requested_model)
        runtime_model = self.runtime_model_id(requested_model)
        await self._raise_if_agent_capped(effective_agent_id)
        payload: dict[str, Any] = {
            "model": runtime_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "include": ["usage"],
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        start = time.monotonic()
        resp = await self._request_with_retry(payload, timeout, stream=True)

        if resp.status_code != 200:
            body = await resp.aread()
            await resp.aclose()
            body_str = body.decode(errors="replace")[:500]
            logger.warning(
                "%s stream error %d: %s",
                self._provider,
                resp.status_code,
                body_str,
            )
            raise LLMError(
                f"{self._provider} returned {resp.status_code}: {body_str}",
                status_code=resp.status_code,
            )

        input_tokens = 0
        output_tokens = 0
        openrouter_id: str | None = None

        try:
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    logger.warning("Malformed SSE chunk (skipping): %s", data_str[:200])
                    continue

                if openrouter_id is None:
                    openrouter_id = chunk.get("id")

                # Extract usage from final chunk if present
                usage = chunk.get("usage")
                if usage:
                    input_tokens = usage.get("prompt_tokens", 0)
                    output_tokens = usage.get("completion_tokens", 0)

                choices = chunk.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                content = delta.get("content", "")
                finish_reason = choices[0].get("finish_reason")

                if content or finish_reason:
                    yield StreamChunk(delta=content or "", finish_reason=finish_reason)
        finally:
            await resp.aclose()
            latency_ms = int((time.monotonic() - start) * 1000)
            cost = self._estimate_call_cost(model_config, input_tokens, output_tokens)

            await self._log_cost(
                effective_agent_id,
                requested_model,
                input_tokens,
                output_tokens,
                cost,
                latency_ms,
                stream=True,
                openrouter_id=openrouter_id,
                simulation_id=simulation_id or self._simulation_id,
                provider=self._provider,
                runtime_model=runtime_model,
            )
            trace_model = runtime_model if self.is_local_provider else requested_model
            self._trace_langfuse(trace_model, input_tokens, output_tokens, latency_ms, cost)


class OfflineTestLLMClient(OpenRouterClient):
    """Deterministic non-network client for pytest bootstrap without provider credentials."""

    def __init__(
        self,
        cost_repo: CostRepo,
        *,
        cost_governor: CostGovernor | None = None,
    ) -> None:
        self._provider = "offline-test"
        self._api_key = ""
        self._base_url = "offline://pytest"
        self._local_model = "offline-test-model"
        self._local_model_building = "offline-test-building-model"
        self._passthrough_model = False
        self._cost_repo = cost_repo
        self._cost_governor = cost_governor
        self._langfuse = None
        self._lost_cost_events = 0
        self._last_cost_failure_ts: float | None = None
        self._total_cost_calls = 0
        self._simulation_id: uuid.UUID | None = None
        self._model_fallbacks: list[dict[str, str]] = []
        self._owns_client = False
        self._turn_counter = 0

    async def close(self) -> None:
        return None

    def _estimate_call_cost(
        self,
        model_config: ModelConfig,
        input_tokens: int,
        output_tokens: int,
    ) -> Decimal:
        estimated = estimate_cost(model_config, input_tokens, output_tokens)
        return max(estimated, OFFLINE_TEST_COST_USD)

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        agent_id: str | None = None,
        *,
        timeout: float = 30.0,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        simulation_id: uuid.UUID | None = None,
    ) -> LLMResponse:
        _ = (timeout, temperature, tools, tool_choice)
        effective_agent_id = agent_id if agent_id is not None else current_agent_id.get()
        requested_model = resolve_model_reference(model, agent_id=effective_agent_id)
        model_config = self._resolve_model(requested_model)
        runtime_model = self.runtime_model_id(requested_model)
        await self._raise_if_agent_capped(effective_agent_id)

        start = time.monotonic()
        content = self._content_for(messages, effective_agent_id)
        if max_tokens is not None:
            content = " ".join(content.split()[:max_tokens])
        latency_ms = int((time.monotonic() - start) * 1000)
        input_tokens = self._count_tokens(messages)
        output_tokens = max(1, len(content.split()))
        cost = self._estimate_call_cost(model_config, input_tokens, output_tokens)
        openrouter_id = f"offline-test-{self._turn_counter}"

        await self._log_cost(
            effective_agent_id,
            requested_model,
            input_tokens,
            output_tokens,
            cost,
            latency_ms,
            stream=False,
            openrouter_id=openrouter_id,
            simulation_id=simulation_id or self._simulation_id,
            provider=self._provider,
            runtime_model=runtime_model,
        )

        return LLMResponse(
            content=content,
            model=requested_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=cost,
            latency_ms=latency_ms,
            openrouter_id=openrouter_id,
            tool_calls=[],
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        agent_id: str | None = None,
        *,
        timeout: float = 30.0,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        simulation_id: uuid.UUID | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        response = await self.complete(
            messages,
            model,
            agent_id,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
            simulation_id=simulation_id,
        )
        yield StreamChunk(delta=response.content, finish_reason="stop")

    def _content_for(self, messages: list[dict[str, str]], agent_id: str | None) -> str:
        self._turn_counter += 1
        combined = "\n".join(str(m.get("content", "")) for m in messages)
        lowered = combined.lower()

        if "content moderation classifier" in lowered:
            return json.dumps(
                {
                    "approved": True,
                    "reason": "offline test client approved deterministic content",
                    "severity": 1,
                }
            )
        if "extract explicit commitments" in lowered:
            return "[]"
        if "respond with only a json object" in lowered and "severity" in lowered:
            return json.dumps({"approved": True, "reason": "offline test", "severity": 1})
        if "json" in lowered and "summary" in lowered:
            return json.dumps(
                {
                    "summary": "The agents completed a short deterministic validation exchange.",
                    "outcomes": ["pipeline validated"],
                    "learnings": ["offline bootstrap can record cost and memory events"],
                }
            )
        if "summary" in lowered or "summarize" in lowered or "journal" in lowered:
            return (
                "The exchange stayed focused on validating the pipeline, recording a "
                "concrete next step, and preserving enough context for recall."
            )

        name = agent_id or "agent"
        return (
            f"{name} advances the test conversation on turn {self._turn_counter}, "
            "names one concrete next step, and leaves room for the other participant to respond."
        )

    @staticmethod
    def _count_tokens(messages: list[dict[str, str]]) -> int:
        return max(
            1,
            sum(len(str(message.get("content", "")).split()) for message in messages),
        )


LLMClient = OpenRouterClient
