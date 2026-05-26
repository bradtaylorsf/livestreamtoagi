"""Cloud providers for the propose_new_building refinement pipeline (#861).

Three providers, one per swappable slot in :class:`RefinementLoop`:

* :class:`OpenAIImageProvider` — OpenAI ``gpt-image-2`` (released 2026-04-21)
  satisfies :class:`ImageProvider`.
* :class:`GeminiVisionDecomposer` — Google ``gemini-3.5-flash`` with
  ``response_mime_type=application/json`` satisfies the
  :class:`DecomposerProvider` contract from
  :mod:`core.minecraft.build_refinement_loop`.
* :class:`GeminiComparisonProvider` — same Gemini model used to compare a
  source blueprint against a build screenshot and emit a structured
  :class:`RefinementFeedback`. Satisfies :class:`VisionComparisonProvider`.

Each provider reads its API key from the environment at construction time so
the call sites stay free of secrets. All three are async and self-contained;
swap in fakes for tests.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from core.minecraft.build_plan import SizeClass, StructureType
from core.minecraft.refinement_feedback import RefinementFeedback

logger = logging.getLogger(__name__)


OPENAI_IMAGE_MODEL = "gpt-image-2"
GEMINI_VISION_MODEL = "gemini-3.5-flash"


class OpenAIImageProvider:
    """Image generation backed by OpenAI ``gpt-image-2``.

    Emits PNG bytes for a single prompt. Cost is reported via
    ``cost_per_call``; the refinement loop honors a per-attempt cap so this
    only needs to be a fair upper-bound estimate, not a billing oracle.
    """

    model_id = OPENAI_IMAGE_MODEL
    cost_per_call = Decimal("0.04")

    def __init__(
        self,
        *,
        api_key: str | None = None,
        size: str = "1024x1024",
        client: Any | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self._api_key:
            raise RuntimeError("OpenAIImageProvider needs OPENAI_API_KEY in the environment.")
        self._size = size
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    async def generate(self, prompt: str) -> bytes:
        client = self._ensure_client()
        response = await client.images.generate(
            model=OPENAI_IMAGE_MODEL,
            prompt=prompt,
            n=1,
            size=self._size,
        )
        data = response.data[0]
        b64 = getattr(data, "b64_json", None)
        if b64:
            return base64.b64decode(b64)
        url = getattr(data, "url", None)
        if url:
            import httpx

            async with httpx.AsyncClient() as http:
                resp = await http.get(url)
                resp.raise_for_status()
                return resp.content
        raise RuntimeError("gpt-image-2 returned no b64_json or url field")


_DECOMPOSER_PROMPT = """You are an architectural decomposer. Look at the
attached building blueprint and emit a structured JSON BuildPlan suitable
for the Livestream→AGI Minecraft compiler.

Required fields (all required, no extras):
- structure_type: one of {structure_types}
- size_class: one of {size_classes}
- source_image_id: copy from intent_hints
- footprint: {{shape:"rectangle"|"circle"|"oval"|"polygon", bbox:{{x:int,y:int,w:int,h:int}}}}
- levels: [{{index:int, height_blocks:int, floor_material:str}}]
- rooms: []  # ALWAYS emit an empty list — do not populate
- materials: [{{region:str, material:str}}] — at minimum floor/walls/roof/frame
- key_features: [{{kind:"column"|"arch"|"roof"|"ornament"|"other", position:{{x:int,y:int,z:int}}, size:{{x:int,y:int,z:int}}}}]
- openings: [{{kind:"door"|"window", position:{{x:int,y:int,z:int}}, level_index:int}}]
- decomposer_version: 1
- provider_model_id: "gemini-3.5-flash"

NOTE: Every key_feature MUST be a JSON object with `kind`, `position`, and
`size` keys — never a bare string. The allowed `kind` is strictly the five
above. Map informal feature names to the closest fit (use "other" if nothing
fits — bartizan/turret/spire -> "other"; crenellation/parapet -> "ornament";
buttress/staircase -> "other").

intent_hints to honor: {hints}

Output ONLY the JSON object."""


class GeminiVisionDecomposer:
    """Decompose a blueprint image into a :class:`BuildPlan` dict via Gemini.

    Implements :class:`DecomposerProvider` from
    :mod:`core.minecraft.build_refinement_loop`. The Gemini client is
    created lazily so importing this module is free.
    """

    model_id = GEMINI_VISION_MODEL
    cost_per_call = Decimal("0.005")

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not self._api_key:
            raise RuntimeError("GeminiVisionDecomposer needs GOOGLE_API_KEY in the environment.")
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        from google import genai

        self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def decompose_bytes(
        self,
        *,
        image_bytes: bytes,
        intent_hints: Mapping[str, Any],
        structure_type: StructureType | str,
        size_class: SizeClass | str,
    ) -> dict[str, Any]:
        from google.genai import types  # type: ignore[import-not-found]

        client = self._ensure_client()
        prompt = _DECOMPOSER_PROMPT.format(
            structure_types=", ".join(sorted(s.value for s in StructureType)),
            size_classes=", ".join(sorted(s.value for s in SizeClass)),
            hints=json.dumps(dict(intent_hints)),
        )

        config = types.GenerateContentConfig(response_mime_type="application/json")
        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/png")
        response = await client.aio.models.generate_content(
            model=GEMINI_VISION_MODEL,
            contents=[image_part, prompt],
            config=config,
        )
        text = response.text or "{}"
        try:
            plan_dict = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("Gemini decomposer returned non-JSON: %s", text[:200])
            raise RuntimeError("Gemini decomposer JSON parse failed") from exc

        plan_dict.setdefault("decomposer_version", 1)
        plan_dict.setdefault("provider_model_id", GEMINI_VISION_MODEL)
        return plan_dict


_COMPARISON_PROMPT = """You are a build-quality reviewer. Compare the SOURCE
blueprint to the BUILD screenshot and emit a structured JSON
RefinementFeedback.

Schema (no extras):
- match_score: float in [0,1] (1.0 = identical)
- feature_deltas: [{{kind:str, expected:bool, actual:bool, note?:str}}]
- per_region_critique: {{region_name: "short critique"}}
- recommended_buildplan_patches: [{{op:"material_reassign"|"level_height_adjust"|"key_feature_add"|"key_feature_remove", region?:str, material?:str, level_index?:int, delta_height?:int, feature_kind?:str, feature_position?:{{x:int,y:int,z:int}}, feature_size?:{{x:int,y:int,z:int}}}}]
- provider_model_id: "gemini-3.5-flash"

Output ONLY the JSON object."""


class GeminiComparisonProvider:
    """Compare blueprint vs build screenshot using Gemini vision.

    Returns a :class:`RefinementFeedback` consumed by the refinement loop to
    patch the live ``BuildPlan`` and re-compile.
    """

    model_id = GEMINI_VISION_MODEL
    cost_per_call = Decimal("0.005")

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not self._api_key:
            raise RuntimeError("GeminiComparisonProvider needs GOOGLE_API_KEY in the environment.")
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        from google import genai

        self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def compare(
        self,
        *,
        source_image_bytes: bytes,
        build_screenshot_bytes: bytes,
        intent_hints: Mapping[str, Any] | None = None,
    ) -> RefinementFeedback:
        from google.genai import types  # type: ignore[import-not-found]

        client = self._ensure_client()
        prompt = _COMPARISON_PROMPT
        if intent_hints:
            prompt = f"{prompt}\n\nintent_hints: {json.dumps(dict(intent_hints))}"

        config = types.GenerateContentConfig(response_mime_type="application/json")
        source_part = types.Part.from_bytes(data=source_image_bytes, mime_type="image/png")
        build_part = types.Part.from_bytes(data=build_screenshot_bytes, mime_type="image/png")
        response = await client.aio.models.generate_content(
            model=GEMINI_VISION_MODEL,
            contents=[
                "SOURCE blueprint:",
                source_part,
                "BUILD screenshot:",
                build_part,
                prompt,
            ],
            config=config,
        )
        text = response.text or "{}"
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("Gemini comparator returned non-JSON: %s", text[:200])
            raise RuntimeError("Gemini comparator JSON parse failed") from exc

        return RefinementFeedback.model_validate(payload)
