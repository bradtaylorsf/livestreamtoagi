"""Async OpenRouter LLM client with cost tracking."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx

from core.models import CostEventCreate, LLMResponse, StreamChunk

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from core.repos.cost_repo import CostRepo

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

RETRYABLE_STATUS_CODES = {429, 500, 502, 503}
MAX_RETRIES = 3
BACKOFF_BASE = 1  # seconds
MAX_RETRY_AFTER = 60  # cap Retry-After header
MODEL_NAME_ALIASES = {
    "deepseek/deepseek-v3.2": "deepseek-v3.2",
}


@dataclass
class ModelConfig:
    openrouter_id: str
    input_price_per_1m: Decimal
    output_price_per_1m: Decimal


# Prices in USD per 1M tokens — update as OpenRouter pricing changes.
MODEL_REGISTRY: dict[str, ModelConfig] = {
    "claude-haiku-4-5": ModelConfig(
        openrouter_id="anthropic/claude-haiku-4-5",
        input_price_per_1m=Decimal("0.80"),
        output_price_per_1m=Decimal("4.00"),
    ),
    "claude-sonnet-4-6": ModelConfig(
        openrouter_id="anthropic/claude-sonnet-4-6",
        input_price_per_1m=Decimal("3.00"),
        output_price_per_1m=Decimal("15.00"),
    ),
    "gemini-flash": ModelConfig(
        openrouter_id="google/gemini-flash-1.5",
        input_price_per_1m=Decimal("0.075"),
        output_price_per_1m=Decimal("0.30"),
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
        input_price_per_1m=Decimal("2.00"),
        output_price_per_1m=Decimal("8.00"),
    ),
    "deepseek-v3.2": ModelConfig(
        openrouter_id="deepseek/deepseek-chat-v3.2",
        input_price_per_1m=Decimal("0.27"),
        output_price_per_1m=Decimal("1.10"),
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


class LLMError(Exception):
    """Raised when an LLM API call fails after retries."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def estimate_cost(
    model_config: ModelConfig, input_tokens: int, output_tokens: int
) -> Decimal:
    return (
        Decimal(input_tokens) * model_config.input_price_per_1m
        + Decimal(output_tokens) * model_config.output_price_per_1m
    ) / Decimal("1000000")


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        cost_repo: CostRepo,
        langfuse_client: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY not set")
        self._api_key = api_key
        self._cost_repo = cost_repo
        self._langfuse = langfuse_client
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://livestreamtoagi.com",
                "X-Title": "Livestream AGI",
            },
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _resolve_model(self, model: str) -> ModelConfig:
        canonical_model = MODEL_NAME_ALIASES.get(model, model)
        if canonical_model not in MODEL_REGISTRY:
            raise ValueError(
                f"Unknown model '{model}'. "
                f"Available: {', '.join(sorted(MODEL_REGISTRY))}"
            )
        return MODEL_REGISTRY[canonical_model]

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
    ) -> None:
        """Fire-and-forget cost logging — never let DB errors break LLM calls."""
        try:
            await self._cost_repo.add_cost(
                CostEventCreate(
                    agent_id=agent_id,
                    cost_type="llm_call",
                    amount=cost,
                    details={
                        "model": model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "latency_ms": latency_ms,
                        "stream": stream,
                        "openrouter_id": openrouter_id,
                    },
                )
            )
        except Exception:
            logger.exception("Failed to log cost event for model=%s agent=%s", model, agent_id)

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
                    "OpenRouter %d on attempt %d/%d, retrying in %.1fs",
                    resp.status_code, attempt + 1, MAX_RETRIES, delay,
                )
                last_exc = LLMError(
                    f"HTTP {resp.status_code}", status_code=resp.status_code
                )
                await asyncio.sleep(delay)
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < MAX_RETRIES - 1:
                    delay = BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        "OpenRouter timeout on attempt %d/%d, retrying in %.1fs",
                        attempt + 1, MAX_RETRIES, delay,
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
    ) -> LLMResponse:
        model_config = self._resolve_model(model)
        payload: dict[str, Any] = {
            "model": model_config.openrouter_id,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        start = time.monotonic()
        resp = await self._request_with_retry(payload, timeout, stream=False)
        latency_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code != 200:
            logger.debug("OpenRouter error body: %s", resp.text)
            raise LLMError(
                f"OpenRouter returned {resp.status_code}",
                status_code=resp.status_code,
            )

        data = resp.json()
        choices = data.get("choices")
        if not choices:
            raise LLMError("OpenRouter returned no choices in response")
        content = choices[0]["message"]["content"] or ""
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        openrouter_id = data.get("id")
        cost = estimate_cost(model_config, input_tokens, output_tokens)

        await self._log_cost(
            agent_id, model, input_tokens, output_tokens, cost, latency_ms,
            stream=False, openrouter_id=openrouter_id,
        )
        self._trace_langfuse(model, input_tokens, output_tokens, latency_ms, cost)

        return LLMResponse(
            content=content,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=cost,
            latency_ms=latency_ms,
            openrouter_id=openrouter_id,
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
    ) -> AsyncGenerator[StreamChunk, None]:
        model_config = self._resolve_model(model)
        payload: dict[str, Any] = {
            "model": model_config.openrouter_id,
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
            logger.debug("OpenRouter stream error body: %s", body.decode(errors="replace"))
            raise LLMError(
                f"OpenRouter returned {resp.status_code}",
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
            cost = estimate_cost(model_config, input_tokens, output_tokens)

            await self._log_cost(
                agent_id, model, input_tokens, output_tokens, cost, latency_ms,
                stream=True, openrouter_id=openrouter_id,
            )
            self._trace_langfuse(model, input_tokens, output_tokens, latency_ms, cost)
