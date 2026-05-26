"""Screenshot capture helper (issue #858).

Asks the live Minecraft bridge to capture a screenshot via a ``!screenshot``
command. Bridges without a screenshot endpoint return an error status; in
that case we still write a placeholder PNG and record
``status="unsupported"`` in the replay manifest so the artifact set is
complete even on the deterministic fake bridge.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# 1×1 transparent PNG — small enough to embed without burning real bytes,
# big enough to verify the manifest path round-trips correctly in tests.
_PLACEHOLDER_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
    b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc"
    b"\x00\x01\x00\x00\x05\x00\x01\x0d\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _Bridge(Protocol):
    async def send_command(self, command_text: str) -> Mapping[str, Any]: ...


@dataclass
class ScreenshotResult:
    path: Path
    status: str  # "ok" | "unsupported" | "error"
    detail: str | None = None


async def capture_screenshot(
    bridge: _Bridge,
    *,
    label: str,
    output_path: Path,
) -> ScreenshotResult:
    """Capture a screenshot and persist it to ``output_path``.

    The bridge is asked to capture the frame via ``!screenshot <label>``;
    when the bridge does not respond with status ``ok`` we fall back to a
    1×1 placeholder PNG so the file still exists. Either way, the result
    object reports the real status so the replay manifest stays accurate.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        response = await bridge.send_command(f"!screenshot {label}")
    except Exception as exc:  # pragma: no cover - bridge can raise transient errors
        logger.warning("screenshot bridge call failed for %s: %s", label, exc)
        output_path.write_bytes(_PLACEHOLDER_PNG)
        return ScreenshotResult(path=output_path, status="error", detail=str(exc))

    status = str(response.get("status", "")).lower() if isinstance(response, Mapping) else ""
    image_bytes = response.get("image_bytes") if isinstance(response, Mapping) else None
    if status == "ok" and isinstance(image_bytes, (bytes, bytearray)):
        output_path.write_bytes(bytes(image_bytes))
        return ScreenshotResult(path=output_path, status="ok")

    detail = None
    if isinstance(response, Mapping):
        detail = response.get("reason") or response.get("error") or response.get("message")
    output_path.write_bytes(_PLACEHOLDER_PNG)
    status_label = "unsupported" if status in {"", "unsupported", "rejected"} else "error"
    return ScreenshotResult(
        path=output_path,
        status=status_label,
        detail=str(detail) if detail is not None else None,
    )


class FakeReplayBridge:
    """Permissive fake bridge for replay dry-runs.

    The :class:`core.minecraft.eval.live_runner.FakeBridgeClient` is
    intentionally strict about its vocabulary (it only knows the seven
    eval command families). Replay sends ``!chat``, ``!setblock``,
    ``!fill``, ``!screenshot``, and ``!goToCoordinates``, so the eval
    fake rejects most of them. This fake accepts anything starting with
    ``!`` and records the call for inspection — exactly what the dry-run
    replay needs.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def send_command(self, command_text: str) -> Mapping[str, Any]:
        self.calls.append(command_text)
        if command_text.startswith("!screenshot"):
            return {"status": "ok", "image_bytes": _PLACEHOLDER_PNG}
        return {"status": "ok", "reason": "fake replay bridge"}


__all__ = ["FakeReplayBridge", "ScreenshotResult", "capture_screenshot"]
