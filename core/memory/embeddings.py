"""Embedding generation via OpenRouter/OpenAI-compatible API."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

EMBEDDING_MODEL = "openai/text-embedding-3-small"
EMBEDDING_DIMENSION = 1536
OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"


async def generate_embedding(
    text: str,
    http_client: httpx.AsyncClient,
    api_key: str,
) -> list[float]:
    """Call OpenRouter embedding API and return a 1536-dimensional vector.

    Raises ``RuntimeError`` on API errors or dimension mismatches.
    """
    response = await http_client.post(
        OPENROUTER_EMBEDDINGS_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"model": EMBEDDING_MODEL, "input": text},
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Embedding API returned {response.status_code}: {response.text}"
        )

    data = response.json()
    embedding: list[float] = data["data"][0]["embedding"]

    if len(embedding) != EMBEDDING_DIMENSION:
        raise RuntimeError(
            f"Expected {EMBEDDING_DIMENSION}-dim embedding, got {len(embedding)}"
        )

    return embedding
