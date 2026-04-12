"""Diagnostics endpoint for cost tracking health."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from core.admin.dependencies import get_llm

if TYPE_CHECKING:
    from core.llm_client import OpenRouterClient

router = APIRouter(tags=["diagnostics"])


@router.get("/diagnostics")
async def get_diagnostics(
    llm: OpenRouterClient = Depends(get_llm),
) -> JSONResponse:
    """Expose cost tracking diagnostics including lost event count."""
    data = llm.diagnostics()

    headers: dict[str, str] = {}
    if data["lost_cost_events"] > 0:
        headers["X-Cost-Data-Loss"] = "true"

    return JSONResponse(content=data, headers=headers)
