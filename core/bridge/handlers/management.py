"""Bridge handler for Management content review."""

from __future__ import annotations

import logging
from typing import Any

from core.bridge.contract import BridgeRequest, ManagementReviewRequest
from core.models import ManagementPolicy

logger = logging.getLogger(__name__)


async def handle_management_review(env: BridgeRequest, services: Any) -> dict[str, Any]:
    """Review candidate bot speech before any Minecraft-visible emission."""
    payload = ManagementReviewRequest.model_validate(env.payload)
    management = services.management

    if getattr(management, "policy", None) == ManagementPolicy.off:
        return {
            "verdict": "allow",
            "reason": "management policy=off",
            "sanitized_text": None,
        }

    review = await management.review(
        agent_id=payload.agent_id,
        content=payload.text,
        simulation_id=env.simulation_id,
    )
    if review.approved:
        return {
            "verdict": "allow",
            "reason": review.reason,
            "sanitized_text": None,
        }

    sanitized_text = review.replacement
    if review.severity == 3 and sanitized_text is None:
        try:
            sanitized_text = await management.generate_replacement(
                payload.agent_id,
                review.reason,
            )
        except Exception:
            logger.warning(
                "Management replacement generation failed; preserving veto",
                exc_info=True,
                extra={"agent_id": payload.agent_id, "severity": review.severity},
            )

    try:
        await management.intervene(
            review.severity,
            payload.agent_id,
            review.reason,
            replacement=sanitized_text,
        )
    except Exception:
        logger.warning(
            "Management intervention failed after review veto",
            exc_info=True,
            extra={"agent_id": payload.agent_id, "severity": review.severity},
        )

    return {
        "verdict": "veto",
        "reason": review.reason,
        "sanitized_text": sanitized_text,
    }
