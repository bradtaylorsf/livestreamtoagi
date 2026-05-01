"""Journal illustration generator using Google Gemini image generation.

Generates pixel-art-style illustrations for agent journal entries,
with per-agent visual style based on personality color and aesthetic.
"""

from __future__ import annotations

import base64
import logging
import os
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from core.repos.cost_repo import CostRepo

logger = logging.getLogger(__name__)

# Gemini image generation pricing (~$0.02 per image)
IMAGEN_COST_PER_IMAGE = Decimal("0.02")
IMAGEN_MODEL = "gemini-2.5-flash-image"
IMAGEN_SIZE = "512x512"

# Agent personality → visual style mapping
AGENT_VISUAL_STYLES: dict[str, str] = {
    "vera": "royal purple tones, elegant and commanding composition",
    "rex": "dark blue and steel gray, technical schematics and machinery",
    "aurora": "vibrant rainbow colors, dreamy and artistic swirls",
    "pixel": "bright green and white, digital screens and chat bubbles",
    "fork": "dark red and black, sharp angles and contrarian symbols",
    "sentinel": "amber and gold, ledgers and careful precision",
    "grok": "electric orange and chaos, memes and viral energy",
    "alpha": "silver and teal, loyal wolf imagery and service",
    "management": "muted gray and surveillance blue, oversight and calm",
}


def build_illustration_prompt(journal_content: str, agent_id: str) -> str:
    """Construct an image generation prompt from journal content and agent personality.

    Combines the journal entry content, agent-specific visual style,
    and pixel art directives into a single prompt.
    """
    style = AGENT_VISUAL_STYLES.get(agent_id, "neutral tones")

    # Take first ~200 chars of journal content for scene context
    scene_hint = journal_content[:200].strip()
    if len(journal_content) > 200:
        scene_hint += "..."

    return (
        f"Pixel art illustration, 16-bit retro game style, {IMAGEN_SIZE}. "
        f"Scene inspired by: {scene_hint} "
        f"Visual style: {style}. "
        f"Clean pixel art with visible pixels, limited color palette, "
        f"no text or letters in the image."
    )


class JournalImageGenerator:
    """Generates illustrations for journal entries using Google Gemini image generation."""

    def __init__(
        self,
        cost_repo: CostRepo | None = None,
        api_key: str | None = None,
        gcs_bucket: str | None = None,
    ) -> None:
        self._api_key = (
            api_key if api_key is not None else os.environ.get("GOOGLE_IMAGEN_API_KEY", "")
        )
        self._gcs_bucket = (
            gcs_bucket if gcs_bucket is not None else os.environ.get("GCS_BUCKET_NAME", "")
        )
        self._cost_repo = cost_repo

    @property
    def is_configured(self) -> bool:
        """Return True if the API key is set."""
        return bool(self._api_key)

    async def generate(
        self,
        journal_content: str,
        agent_id: str,
        simulation_id: uuid.UUID | None = None,
    ) -> str | None:
        """Generate a pixel-art illustration for a journal entry.

        Returns the image URL on success, or None if generation fails.
        Never raises — failures are logged and return None so the
        journal entry is saved without an image.
        """
        if not self.is_configured:
            logger.debug("Imagen API key not configured, skipping illustration")
            return None

        try:
            prompt = build_illustration_prompt(journal_content, agent_id)
            image_bytes = await self._call_imagen_api(prompt)
            if image_bytes is None:
                return None

            image_url = await self._upload_to_gcs(image_bytes, agent_id)
            await self._log_cost(agent_id, simulation_id, prompt)
            return image_url

        except Exception:
            logger.exception("Failed to generate journal illustration for agent=%s", agent_id)
            return None

    async def _call_imagen_api(self, prompt: str) -> bytes | None:
        """Call Gemini generateContent API and return raw image bytes."""
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{IMAGEN_MODEL}:generateContent"
        )
        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "imageConfig": {
                    "aspectRatio": "1:1",
                },
            },
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            logger.warning("Gemini image API returned no candidates")
            return None

        # Extract image from response parts
        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            inline_data = part.get("inlineData") or part.get("inline_data")
            if (
                inline_data
                and inline_data.get("mimeType", inline_data.get("mime_type", "")) == "image/png"
            ):
                b64_image = inline_data.get("data", "")
                if b64_image:
                    return base64.b64decode(b64_image)

        logger.warning("Gemini image API returned no image data in response parts")
        return None

    async def _upload_to_gcs(self, image_bytes: bytes, agent_id: str) -> str:
        """Upload image bytes to GCS and return the public URL.

        If no GCS bucket is configured, falls back to a data URI
        (suitable for development/testing).
        """
        filename = f"journal-illustrations/{agent_id}/{uuid.uuid4().hex}.png"

        if not self._gcs_bucket:
            logger.debug("No GCS bucket configured, using base64 data URI fallback")
            b64 = base64.b64encode(image_bytes).decode()
            return f"data:image/png;base64,{b64}"

        upload_url = (
            f"https://storage.googleapis.com/upload/storage/v1/b/"
            f"{self._gcs_bucket}/o?uploadType=media&name={filename}"
        )
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "image/png",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(upload_url, content=image_bytes, headers=headers)
            resp.raise_for_status()

        return f"https://storage.googleapis.com/{self._gcs_bucket}/{filename}"

    async def _log_cost(
        self,
        agent_id: str,
        simulation_id: uuid.UUID | None,
        prompt: str,
    ) -> None:
        """Log the image generation cost event."""
        if self._cost_repo is None:
            return

        from core.models import CostEventCreate

        cost = CostEventCreate(
            agent_id=agent_id,
            cost_type="imagen_generation",
            amount=IMAGEN_COST_PER_IMAGE,
            details={
                "model": IMAGEN_MODEL,
                "size": IMAGEN_SIZE,
                "prompt": prompt[:500],
            },
            simulation_id=simulation_id,
        )
        try:
            await self._cost_repo.add_cost(cost)
        except Exception:
            logger.exception("Failed to log imagen cost for agent=%s", agent_id)
