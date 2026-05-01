"""Embedding generation via OpenRouter/OpenAI-compatible API."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "openai/text-embedding-3-small"
EMBEDDING_DIMENSION = 1536
OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"
LOCAL_EMBEDDINGS_BASE_URL = "http://localhost:1234/v1"
LOCAL_EMBEDDING_MODEL = "text-embedding-nomic-embed-text-v1.5"
LOCAL_EMBEDDING_API_KEY = "lm-studio"

# Retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY = 0.5  # seconds
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class EmbeddingProviderConfig:
    """Configuration for OpenAI-compatible embedding generation."""

    provider: str
    url: str
    model: str
    api_key: str
    dimension: int = EMBEDDING_DIMENSION


def _join_embeddings_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/embeddings") else f"{base}/embeddings"


def embedding_config_from_env(openrouter_api_key: str = "") -> EmbeddingProviderConfig:
    """Build embedding config from environment variables.

    Defaults preserve the current OpenRouter behavior. When LLM_PROVIDER is a
    local provider and EMBEDDING_PROVIDER is unset, deterministic embeddings are
    used so local smoke tests can verify pipeline plumbing without token spend.
    Set EMBEDDING_PROVIDER=lmstudio and LOCAL_EMBEDDING_MODEL to test real local
    semantic embeddings.
    """
    llm_provider = os.environ.get("LLM_PROVIDER", "openrouter").strip().lower()
    default_provider = (
        "deterministic"
        if llm_provider
        in {
            "local",
            "lmstudio",
            "lm-studio",
            "lm_studio",
            "openai-compatible",
            "openai_compatible",
        }
        else "openrouter"
    )
    provider_raw = os.environ.get("EMBEDDING_PROVIDER")
    provider = (
        provider_raw.strip().lower()
        if provider_raw is not None and provider_raw.strip()
        else default_provider
    )

    if provider == "openrouter":
        return EmbeddingProviderConfig(
            provider="openrouter",
            url=OPENROUTER_EMBEDDINGS_URL,
            model=os.environ.get("EMBEDDING_MODEL", EMBEDDING_MODEL),
            api_key=os.environ.get("EMBEDDING_API_KEY", openrouter_api_key),
        )

    if provider in {"local", "lmstudio", "lm-studio", "lm_studio", "openai-compatible"}:
        base_url = os.environ.get(
            "EMBEDDING_BASE_URL",
            os.environ.get("LOCAL_EMBEDDING_BASE_URL", LOCAL_EMBEDDINGS_BASE_URL),
        )
        return EmbeddingProviderConfig(
            provider="lmstudio" if provider.startswith("lm") or provider == "local" else provider,
            url=_join_embeddings_url(base_url),
            model=os.environ.get("LOCAL_EMBEDDING_MODEL", LOCAL_EMBEDDING_MODEL),
            api_key=os.environ.get(
                "EMBEDDING_API_KEY",
                os.environ.get("LOCAL_LLM_API_KEY", LOCAL_EMBEDDING_API_KEY),
            ),
        )

    if provider == "deterministic":
        return EmbeddingProviderConfig(
            provider="deterministic",
            url="deterministic://local",
            model="deterministic-hash-embedding",
            api_key="",
        )

    raise ValueError(
        f"Unknown EMBEDDING_PROVIDER '{provider}'. "
        "Use 'openrouter', 'lmstudio', 'openai-compatible', or 'deterministic'."
    )


def generate_deterministic_embedding(
    text: str,
    dimension: int = EMBEDDING_DIMENSION,
) -> list[float]:
    """Generate a stable nonzero embedding for local pipeline smoke tests.

    This is not semantic. It exists so archival/recall/dream persistence can be
    verified without a paid or locally loaded embedding model.
    """
    values: list[float] = []
    seed = text.encode("utf-8", errors="ignore") or b"empty"
    counter = 0
    while len(values) < dimension:
        digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        for byte in digest:
            values.append((byte / 127.5) - 1.0)
            if len(values) == dimension:
                break
        counter += 1

    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


async def generate_embedding(
    text: str,
    http_client: httpx.AsyncClient,
    api_key: str,
    *,
    url: str = OPENROUTER_EMBEDDINGS_URL,
    model: str = EMBEDDING_MODEL,
    expected_dimension: int = EMBEDDING_DIMENSION,
) -> list[float]:
    """Call an OpenAI-compatible embedding API and return a vector.

    Retries up to MAX_RETRIES times with exponential backoff for transient
    failures (429, 5xx, connection errors).

    Raises ``RuntimeError`` on persistent API errors or dimension mismatches.
    """
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            response = await http_client.post(
                url,
                headers=headers,
                json={"model": model, "input": text},
            )

            if response.status_code == 200:
                data = response.json()
                embedding: list[float] = data["data"][0]["embedding"]

                if len(embedding) != expected_dimension:
                    raise RuntimeError(
                        f"Expected {expected_dimension}-dim embedding, got {len(embedding)}"
                    )

                return embedding

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    "Embedding API returned %d, retrying in %.1fs (attempt %d/%d)",
                    response.status_code,
                    delay,
                    attempt + 1,
                    MAX_RETRIES,
                )
                await asyncio.sleep(delay)
                continue

            raise RuntimeError(f"Embedding API returned {response.status_code}: {response.text}")

        except RuntimeError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    "Embedding API connection error, retrying in %.1fs (attempt %d/%d): %s",
                    delay,
                    attempt + 1,
                    MAX_RETRIES,
                    exc,
                )
                await asyncio.sleep(delay)
            else:
                raise RuntimeError(
                    f"Embedding API failed after {MAX_RETRIES + 1} attempts: {last_error}"
                ) from last_error

    # Should not be reached, but satisfies type checker
    raise RuntimeError(f"Embedding API failed after {MAX_RETRIES + 1} attempts: {last_error}")
