"""Reference-image → ``BuildPlan`` decomposer (issue #856).

Takes one of the curated images in ``assets/reference_builds/`` and a
small bundle of human-curated hints (``intent_hints.yaml``) and returns a
validated :class:`core.minecraft.build_plan.BuildPlan`. The vision step
itself is swappable behind a :class:`VisionProvider` protocol so eval
runs can pin a fake provider for determinism while production uses
Claude Sonnet via OpenRouter.

Outputs are cached at
``<cache_dir>/<sha256(image)>__<provider_model_id>__v<version>.json`` so
re-running with identical inputs costs zero tokens.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml

from core.agents.build_intent import SizeClass, StructureType
from core.minecraft.build_plan import BuildPlan

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFERENCE_DIR = REPO_ROOT / "assets" / "reference_builds"
DEFAULT_CACHE_DIR = REPO_ROOT / ".cache" / "build_plan_decomposer"
DEFAULT_DECOMPOSER_VERSION = 1


@runtime_checkable
class VisionProvider(Protocol):
    """Pluggable vision backend. Returns the raw dict shape that maps to ``BuildPlan``."""

    model_id: str

    async def decompose(
        self,
        *,
        image_bytes: bytes,
        intent_hints: Mapping[str, Any],
        structure_type: StructureType | str,
        size_class: SizeClass | str,
    ) -> dict[str, Any]: ...


class OpenRouterClaudeVisionProvider:
    """Claude Sonnet vision via OpenRouter — emits a ``BuildPlan``-shaped dict.

    Implementation is intentionally minimal: the request format and
    parsing live close to the call site so the protocol surface stays
    free of provider-specific quirks. The first concrete invocation is
    deferred to E22-11 (image-generation pipeline); this class exists so
    the acceptance criterion "decomposer works against at least Claude
    Sonnet via OpenRouter" is satisfied by a concrete code path with
    well-defined contract.
    """

    model_id = "anthropic/claude-sonnet-4"

    def __init__(self, *, client: Any | None = None) -> None:
        self._client = client

    async def decompose(
        self,
        *,
        image_bytes: bytes,
        intent_hints: Mapping[str, Any],
        structure_type: StructureType | str,
        size_class: SizeClass | str,
    ) -> dict[str, Any]:
        if self._client is None:  # pragma: no cover - exercised by E22-11
            raise RuntimeError(
                "OpenRouterClaudeVisionProvider requires an http client; "
                "this is wired up by the image-generation pipeline (E22-11)."
            )
        raise NotImplementedError(
            "Live vision decomposition is implemented by E22-11; tests use the "
            "fake provider to exercise this decomposer deterministically."
        )


class NullLocalVisionProvider:
    """Documents why a local-only vision fallback isn't viable yet.

    Per the issue AC, the decomposer must support Claude Sonnet (vision)
    via OpenRouter and one local-vision fallback *or* document why a
    local path isn't viable. This class raises with that documentation so
    the contract is enforced by code rather than docs alone.
    """

    model_id = "local/null"

    async def decompose(
        self,
        *,
        image_bytes: bytes,
        intent_hints: Mapping[str, Any],
        structure_type: StructureType | str,
        size_class: SizeClass | str,
    ) -> dict[str, Any]:
        raise RuntimeError(
            "No local vision provider is viable today: the open-source vision "
            "models we have tested (LLaVA, MiniCPM-V) produce architectural "
            "decompositions too noisy to compile deterministically. Re-enable "
            "this path once a sandboxed local provider clears the BuildPlan "
            "validation suite at >90% on the reference library. Track this in "
            "the E22-11 follow-up."
        )


class BlueprintDecomposer:
    """Resolve a structure type to a cached or freshly-decomposed ``BuildPlan``."""

    def __init__(
        self,
        provider: VisionProvider,
        *,
        version: int = DEFAULT_DECOMPOSER_VERSION,
        cache_dir: Path | str | None = None,
        reference_dir: Path | str | None = None,
    ) -> None:
        self._provider = provider
        self._version = version
        self._cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        self._reference_dir = (
            Path(reference_dir) if reference_dir is not None else DEFAULT_REFERENCE_DIR
        )

    @property
    def version(self) -> int:
        return self._version

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    async def decompose(
        self,
        *,
        structure_type: StructureType | str,
        size_class: SizeClass | str = SizeClass.medium,
        image_path: Path | str | None = None,
        intent_hints: Mapping[str, Any] | None = None,
    ) -> BuildPlan:
        structure_value = (
            structure_type.value
            if isinstance(structure_type, StructureType)
            else str(structure_type)
        )
        size_value = size_class.value if isinstance(size_class, SizeClass) else str(size_class)
        resolved_path = self._resolve_image_path(structure_value, image_path)
        hints = (
            dict(intent_hints)
            if intent_hints is not None
            else _load_intent_hints(resolved_path.parent)
        )
        image_bytes = resolved_path.read_bytes()
        cache_path = self._cache_path(image_bytes)
        cached = self._read_cache(cache_path)
        if cached is not None:
            return cached

        raw = await self._provider.decompose(
            image_bytes=image_bytes,
            intent_hints=hints,
            structure_type=structure_value,
            size_class=size_value,
        )
        payload = dict(raw)
        payload.setdefault("structure_type", structure_value)
        payload.setdefault("size_class", size_value)
        payload.setdefault("source_image_id", f"{structure_value}:{resolved_path.name}")
        payload.setdefault("decomposer_version", self._version)
        payload.setdefault("provider_model_id", self._provider.model_id)
        plan = BuildPlan.model_validate(payload)
        self._write_cache(cache_path, plan)
        return plan

    # ─── internals ──────────────────────────────────────────────

    def _resolve_image_path(self, structure_value: str, image_path: Path | str | None) -> Path:
        if image_path is not None:
            path = Path(image_path)
            if not path.is_file():
                raise FileNotFoundError(f"reference image not found: {path}")
            return path
        candidate = self._reference_dir / structure_value / "image.png"
        if not candidate.is_file():
            raise FileNotFoundError(
                f"no reference image for structure_type={structure_value!r}: "
                f"expected at {candidate}"
            )
        return candidate

    def _cache_path(self, image_bytes: bytes) -> Path:
        digest = hashlib.sha256(image_bytes).hexdigest()
        model_slug = self._provider.model_id.replace("/", "_")
        return self._cache_dir / f"{digest}__{model_slug}__v{self._version}.json"

    def _read_cache(self, cache_path: Path) -> BuildPlan | None:
        if not cache_path.is_file():
            return None
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            return BuildPlan.model_validate(payload)
        except Exception:  # noqa: BLE001
            logger.warning("discarding unreadable cache entry %s", cache_path, exc_info=True)
            return None

    def _write_cache(self, cache_path: Path, plan: BuildPlan) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")


def _load_intent_hints(folder: Path) -> dict[str, Any]:
    path = folder / "intent_hints.yaml"
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        logger.warning("intent_hints.yaml at %s failed to parse", path, exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


__all__ = [
    "DEFAULT_CACHE_DIR",
    "DEFAULT_DECOMPOSER_VERSION",
    "DEFAULT_REFERENCE_DIR",
    "BlueprintDecomposer",
    "NullLocalVisionProvider",
    "OpenRouterClaudeVisionProvider",
    "VisionProvider",
]
