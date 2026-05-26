"""Image-generation for dream-up buildings (issue #861).

Turns a :class:`core.agents.new_building_intent.NewBuildingIntent` into a
locked-vocabulary, blueprint-style image prompt and an image. Free text from
the agent is *not* interpolated into the image prompt — every interpolated
value is enum-validated or has already passed
:class:`NewBuildingIntent`'s strict regex.

Outputs are cached at::

    <cache_dir>/<sha256(prompt + provider + model + version)>__<provider>__v<n>.png

so re-running an identical concept skips the image-gen call entirely.
"""

from __future__ import annotations

import hashlib
import logging
from decimal import Decimal
from pathlib import Path
from typing import Protocol, runtime_checkable

from core.agents.new_building_intent import NewBuildingIntent

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = REPO_ROOT / ".cache" / "blueprint_generator"
DEFAULT_PROMPT_VERSION = 1

_SIZE_LABELS = {
    "small": "approx. 8x8 meters",
    "medium": "approx. 16x16 meters",
    "large": "approx. 32x32 meters",
    "epic": "approx. 64x64 meters or larger",
}

IMAGE_PROMPT_TEMPLATE = (
    "Top-down architectural blueprint of {concept}. "
    "Style: {vibe}. "
    "Biome context: {biome_fit}. "
    "Intended footprint: {size_label}. "
    "Scale: 1 grid square = 1 meter. "
    "Render as a clean blueprint: neutral white background, black ink "
    "linework, dimension callouts at corners, and a north arrow. "
    "Show structural shell, walls, and roof footprint. Do not include "
    "people, animals, vehicles, signage, or text labels beyond dimension "
    "callouts. No photorealistic rendering, no perspective."
)


def _size_label(size_class: str) -> str:
    return _SIZE_LABELS.get(size_class, "approx. 16x16 meters")


def build_image_prompt(intent: NewBuildingIntent) -> str:
    """Render the locked image prompt for ``intent``.

    The intent's pydantic validators already restricted ``concept`` to a
    safe character set and gated ``vibe``, ``biome_fit``, ``size_class``
    against enums; this function never accepts a raw string from a caller.
    """
    return IMAGE_PROMPT_TEMPLATE.format(
        concept=intent.concept,
        vibe=intent.vibe,
        biome_fit=intent.biome_fit,
        size_label=_size_label(intent.size_class),
    )


@runtime_checkable
class ImageProvider(Protocol):
    """Pluggable image-gen backend."""

    model_id: str
    cost_per_call: Decimal

    async def generate(self, prompt: str) -> bytes: ...


# 1x1 transparent PNG — same constant used by the screenshot helper.
_DETERMINISTIC_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
    b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc"
    b"\x00\x01\x00\x00\x05\x00\x01\x0d\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FakeImageProvider:
    """Deterministic stub used by tests and the dry-run path."""

    model_id = "fake/blueprint-image"
    cost_per_call = Decimal("0")

    def __init__(self, payload: bytes | None = None) -> None:
        self._payload = payload or _DETERMINISTIC_PNG
        self.calls: list[str] = []

    async def generate(self, prompt: str) -> bytes:
        self.calls.append(prompt)
        return self._payload


class OpenAIImagesProvider:
    """OpenAI Images backend (``gpt-image-1``).

    Constructed with an injected async ``http_post`` callable so tests can
    pin the response without importing ``httpx``. Production wires this
    up to ``httpx.AsyncClient.post`` against ``api.openai.com``.
    """

    model_id = "openai/gpt-image-1"
    cost_per_call = Decimal("0.04")

    def __init__(
        self,
        *,
        api_key: str,
        http_post: object | None = None,
        endpoint: str = "https://api.openai.com/v1/images/generations",
    ) -> None:
        if not api_key:
            raise ValueError("OpenAIImagesProvider requires a non-empty api_key")
        self._api_key = api_key
        self._http_post = http_post
        self._endpoint = endpoint

    async def generate(self, prompt: str) -> bytes:  # pragma: no cover - live path
        if self._http_post is None:
            raise RuntimeError(
                "OpenAIImagesProvider requires an http_post callable; pass one "
                "in for live use, or use FakeImageProvider for tests."
            )
        import base64

        response = await self._http_post(  # type: ignore[misc]
            self._endpoint,
            json={
                "model": "gpt-image-1",
                "prompt": prompt,
                "size": "1024x1024",
                "n": 1,
            },
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        payload = response.json() if hasattr(response, "json") else response
        data = payload.get("data") or []
        if not data:
            raise RuntimeError("OpenAI Images response missing 'data' array")
        b64 = data[0].get("b64_json")
        if not isinstance(b64, str):
            raise RuntimeError("OpenAI Images response missing b64_json")
        return base64.b64decode(b64)


class BlueprintGenerator:
    """Cache-aware image generator for new-building intents."""

    def __init__(
        self,
        provider: ImageProvider,
        *,
        version: int = DEFAULT_PROMPT_VERSION,
        cache_dir: Path | str | None = None,
    ) -> None:
        self._provider = provider
        self._version = version
        self._cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR

    @property
    def version(self) -> int:
        return self._version

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    @property
    def provider_model_id(self) -> str:
        return self._provider.model_id

    @property
    def cost_per_call(self) -> Decimal:
        return self._provider.cost_per_call

    async def generate(self, intent: NewBuildingIntent) -> tuple[bytes, str, bool]:
        """Return ``(image_bytes, prompt, cache_hit)`` for ``intent``."""
        prompt = build_image_prompt(intent)
        cache_path = self._cache_path(prompt)
        if cache_path.is_file():
            return cache_path.read_bytes(), prompt, True
        image_bytes = await self._provider.generate(prompt)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(image_bytes)
        return image_bytes, prompt, False

    def _cache_path(self, prompt: str) -> Path:
        digest = hashlib.sha256(
            (prompt + "|" + self._provider.model_id + "|" + str(self._version)).encode("utf-8")
        ).hexdigest()
        provider_slug = self._provider.model_id.replace("/", "_")
        return self._cache_dir / f"{digest}__{provider_slug}__v{self._version}.png"


__all__ = [
    "DEFAULT_CACHE_DIR",
    "DEFAULT_PROMPT_VERSION",
    "IMAGE_PROMPT_TEMPLATE",
    "BlueprintGenerator",
    "FakeImageProvider",
    "ImageProvider",
    "OpenAIImagesProvider",
    "build_image_prompt",
]
