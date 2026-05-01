"""Tests for embedding generation with retry logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.memory.embeddings import (
    EMBEDDING_DIMENSION,
    MAX_RETRIES,
    embedding_config_from_env,
    generate_deterministic_embedding,
    generate_embedding,
)


def _make_success_response(dim: int = EMBEDDING_DIMENSION) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "data": [{"embedding": [0.1] * dim}]
    }
    return response


def _make_error_response(status_code: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = f"Error {status_code}"
    return response


class TestGenerateEmbedding:
    """Tests for generate_embedding with retry logic."""

    @pytest.mark.asyncio
    async def test_successful_embedding(self) -> None:
        client = AsyncMock()
        client.post.return_value = _make_success_response()

        result = await generate_embedding("test text", client, "api-key")

        assert len(result) == EMBEDDING_DIMENSION
        assert all(v == 0.1 for v in result)

    @pytest.mark.asyncio
    async def test_retries_on_429(self) -> None:
        client = AsyncMock()
        client.post.side_effect = [
            _make_error_response(429),
            _make_success_response(),
        ]

        with patch("core.memory.embeddings.asyncio.sleep", new_callable=AsyncMock):
            result = await generate_embedding("test", client, "key")

        assert len(result) == EMBEDDING_DIMENSION
        assert client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_500(self) -> None:
        client = AsyncMock()
        client.post.side_effect = [
            _make_error_response(500),
            _make_error_response(503),
            _make_success_response(),
        ]

        with patch("core.memory.embeddings.asyncio.sleep", new_callable=AsyncMock):
            result = await generate_embedding("test", client, "key")

        assert len(result) == EMBEDDING_DIMENSION
        assert client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_fails_after_max_retries(self) -> None:
        client = AsyncMock()
        client.post.return_value = _make_error_response(500)

        with (
            patch("core.memory.embeddings.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(RuntimeError, match="500"),
        ):
            await generate_embedding("test", client, "key")

        assert client.post.call_count == MAX_RETRIES + 1

    @pytest.mark.asyncio
    async def test_no_retry_on_400(self) -> None:
        client = AsyncMock()
        client.post.return_value = _make_error_response(400)

        with pytest.raises(RuntimeError, match="400"):
            await generate_embedding("test", client, "key")

        assert client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self) -> None:
        client = AsyncMock()
        client.post.side_effect = [
            ConnectionError("Connection refused"),
            _make_success_response(),
        ]

        with patch("core.memory.embeddings.asyncio.sleep", new_callable=AsyncMock):
            result = await generate_embedding("test", client, "key")

        assert len(result) == EMBEDDING_DIMENSION

    @pytest.mark.asyncio
    async def test_fails_on_dimension_mismatch(self) -> None:
        client = AsyncMock()
        client.post.return_value = _make_success_response(dim=768)

        with pytest.raises(RuntimeError, match="Expected 1536"):
            await generate_embedding("test", client, "key")

    @pytest.mark.asyncio
    async def test_connection_error_exhausts_retries(self) -> None:
        client = AsyncMock()
        client.post.side_effect = ConnectionError("refused")

        with (
            patch("core.memory.embeddings.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(RuntimeError, match="failed after"),
        ):
            await generate_embedding("test", client, "key")

        assert client.post.call_count == MAX_RETRIES + 1


def test_deterministic_embedding_is_stable_and_nonzero() -> None:
    first = generate_deterministic_embedding("memory fragment")
    second = generate_deterministic_embedding("memory fragment")

    assert first == second
    assert len(first) == EMBEDDING_DIMENSION
    assert any(value != 0 for value in first)


def test_local_llm_defaults_to_deterministic_embeddings() -> None:
    with patch.dict("os.environ", {"LLM_PROVIDER": "lmstudio", "EMBEDDING_PROVIDER": ""}):
        cfg = embedding_config_from_env("")

    assert cfg.provider == "deterministic"


def test_lmstudio_embedding_config_uses_local_endpoint() -> None:
    with patch.dict(
        "os.environ",
        {
            "EMBEDDING_PROVIDER": "lmstudio",
            "LOCAL_EMBEDDING_BASE_URL": "http://localhost:1234/v1",
            "LOCAL_EMBEDDING_MODEL": "nomic-local",
        },
    ):
        cfg = embedding_config_from_env("")

    assert cfg.provider == "lmstudio"
    assert cfg.url == "http://localhost:1234/v1/embeddings"
    assert cfg.model == "nomic-local"
