"""Embedding generation via OpenRouter/OpenAI-compatible API."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "openai/text-embedding-3-small"
EMBEDDING_DIMENSION = 1536
OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"

# Retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY = 0.5  # seconds
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


async def generate_embedding(
    text: str,
    http_client: httpx.AsyncClient,
    api_key: str,
) -> list[float]:
    """Call OpenRouter embedding API and return a 1536-dimensional vector.

    Retries up to MAX_RETRIES times with exponential backoff for transient
    failures (429, 5xx, connection errors).

    Raises ``RuntimeError`` on persistent API errors or dimension mismatches.
    """
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await http_client.post(
                OPENROUTER_EMBEDDINGS_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": EMBEDDING_MODEL, "input": text},
            )

            if response.status_code == 200:
                data = response.json()
                embedding: list[float] = data["data"][0]["embedding"]

                if len(embedding) != EMBEDDING_DIMENSION:
                    raise RuntimeError(
                        f"Expected {EMBEDDING_DIMENSION}-dim embedding, got {len(embedding)}"
                    )

                return embedding

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Embedding API returned %d, retrying in %.1fs (attempt %d/%d)",
                    response.status_code, delay, attempt + 1, MAX_RETRIES,
                )
                await asyncio.sleep(delay)
                continue

            raise RuntimeError(
                f"Embedding API returned {response.status_code}: {response.text}"
            )

        except RuntimeError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Embedding API connection error, retrying in %.1fs (attempt %d/%d): %s",
                    delay, attempt + 1, MAX_RETRIES, exc,
                )
                await asyncio.sleep(delay)
            else:
                raise RuntimeError(
                    f"Embedding API failed after {MAX_RETRIES + 1} attempts: {last_error}"
                ) from last_error

    # Should not be reached, but satisfies type checker
    raise RuntimeError(f"Embedding API failed after {MAX_RETRIES + 1} attempts: {last_error}")
